"""Phase110 API QA restricted to its private synthetic bootstrap fixture.
Credentials are read from an ignored file and never printed. Browser ballot
verification runs between prepare and finish; no Phase109 driver is reused.
"""
import argparse,json,sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.phase110_release_qa import SLUG,METHODS,USERNAMES

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','finish'));parser.add_argument('--base-url',required=True);parser.add_argument('--fixture',required=True);parser.add_argument('--credentials',required=True);parser.add_argument('--site',choices=('manual','worker'),required=True);parser.add_argument('--output',required=True);parser.add_argument('--require-browser-ballots',action='store_true');args=parser.parse_args()
    assert args.base_url in ('http://127.0.0.1:8002','https://www.liquiddemocracy.us')
    fixture=json.loads(Path(args.fixture).read_text(encoding='utf-8'));assert fixture['org_slug']==SLUG and len(fixture['accounts'])==4
    passwords=json.loads(Path(args.credentials).read_text(encoding='utf-8'))['passwords']
    ids={u['username']:u['id'] for u in fixture['accounts']};assert set(ids)==set(USERNAMES)
    clients={}
    for username in USERNAMES:
        c=httpx.Client(base_url=args.base_url,timeout=45)
        r=c.post('/api/auth/login',data={'username':username,'password':passwords[username]});assert r.status_code==200,r.status_code
        c.headers['Authorization']='Bearer '+r.json()['access_token'];clients[username]=c
    owner=clients[USERNAMES[0]];path=f'/api/orgs/{SLUG}/elections';output=Path(args.output)
    def request(client,method,url,**kwargs):
        r=client.request(method,url,**kwargs);assert r.status_code in (200,201,204),(method,url,r.status_code,r.text[:500]);return r.json() if r.content else None
    if args.action=='prepare':
        assert not output.exists(),'Manifest exists; preserving fixtures'
        proposals={}
        for method in METHODS:
            p=request(owner,'POST',path,json={'title_id':fixture['titles'][args.site][method],'voting_method':method})
            pid=p['id'];assert p['voting_rules']['method']==method and 'tie_seed' not in p['voting_rules']
            for username in USERNAMES[1:]:request(clients[username],'POST',f'{path}/{pid}/candidacies')
            p=request(owner,'POST',f'/api/proposals/{pid}/advance',json={});assert p['status']=='voting' and len(p['options'])==3
            assert p['options'][1]['label']==ids[USERNAMES[2]]
            proposals[method]=pid
            output.write_text(json.dumps(proposals,indent=2),encoding='utf-8')
        print(json.dumps({'prepared':proposals,'org_slug':SLUG,'site':args.site},indent=2))
    else:
        proposals=json.loads(output.read_text(encoding='utf-8'));assert set(proposals)==set(METHODS)
        results={}
        for method,pid in proposals.items():
            p=request(owner,'GET',f'/api/proposals/{pid}');assert p['author_id']==ids[USERNAMES[0]] and p['sub_org_id'] is None and p['is_election'] and p['voting_method']==method and p['election_title_id']==fixture['titles'][args.site][method]
            if p['status']=='voting':
                if args.require_browser_ballots:
                    vote=request(owner,'GET',f'/api/proposals/{pid}/my-vote');assert vote['is_direct'] is True,'Cast the steward ballot through the browser first'
                winning_option=next(o['id'] for o in p['options'] if o['label']==ids[USERNAMES[2]])
                payload={'rank_groups':[[winning_option]]} if method=='ranked_pairs' else {('grades' if method=='majority_judgment' else 'scores'):{winning_option:5}}
                for username in USERNAMES[1:]:request(clients[username],'POST',f'/api/proposals/{pid}/vote',json=payload)
                if args.site=='manual':
                    url=f'/api/orgs/{SLUG}/proposals/{pid}/advance' if method in ('score','majority_judgment') else f'/api/proposals/{pid}/advance'
                    p=request(owner,'POST',url,json={});assert p['status']=='passed'
            if args.site=='manual':
                tally=request(owner,'GET',f'/api/proposals/{pid}/results');outcome=tally['method_result']['election']
                assert outcome['winner_user_id']==ids[USERNAMES[2]] and outcome['installation']=='installed'
                assert tally['option_labels'][outcome['counting_winner_option_id']]=='Bea Fictional'
                results[method]={'proposal_id':pid,'winner':'Bea Fictional','installation':outcome['installation'],'finalized':tally['method_result']['finalized']}
            else:results[method]={'proposal_id':pid,'ballots_ready_for_scoped_worker':True}
        print(json.dumps(results,indent=2))
    for c in clients.values():c.close()
if __name__=='__main__':main()
