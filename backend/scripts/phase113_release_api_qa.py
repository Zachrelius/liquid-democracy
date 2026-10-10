"""Fresh Phase 113 normal-API fixtures; credentials never printed.
Prepare leaves manual/ordinary steward ballots for Chrome. Worker ballots are
created through normal authentication/API and closed only by the scoped helper.
"""
import argparse,json,sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.phase113_release_qa import SLUG,METHODS,USERNAMES,require

def ballot(method,options,ids=None):
    if ids:
        ordered=[next(o['id'] for o in options if o['label']==ids[u]) for u in USERNAMES[1:3]]
    else:ordered=[next(o['id'] for o in options if o['label']==name) for name in ('Rain garden','Library evening')]
    return {'rank_groups':[[o] for o in ordered]} if method=='ranked_pairs' else {'grades' if method=='majority_judgment' else 'scores':dict(zip(ordered,(5,3)))}

def run(args):
    require(args.base_url in ('http://127.0.0.1:8002','https://www.liquiddemocracy.us'),'Explicit supported URL required')
    fixture=json.loads(Path(args.fixture).read_text(encoding='utf-8'))
    passwords=json.loads(Path(args.credentials).read_text(encoding='utf-8'))['passwords']
    require(fixture['org_slug']==SLUG and len(fixture['accounts'])==4,'Exact fresh fixture required')
    ids={u['username']:u['id'] for u in fixture['accounts']};require(set(ids)==set(USERNAMES),'Exact accounts required')
    clients={}
    def request(client,method,path,expected=200,**kwargs):
        r=client.request(method,path,**kwargs)
        require(r.status_code==expected,f'QA {method} {path}: expected {expected}, got {r.status_code}')
        return r.json() if r.content else None
    try:
        for username in USERNAMES:
            c=httpx.Client(base_url=args.base_url,timeout=60);clients[username]=c
            login=request(c,'POST','/api/auth/login',data={'username':username,'password':passwords[username]})
            c.headers['Authorization']='Bearer '+login['access_token']
            user=request(c,'GET','/api/auth/me');require(user['username']==username and not user['is_admin'],'Wrong account')
        owner=clients[USERNAMES[0]];root=f'/api/orgs/{SLUG}';output=Path(args.output)
        if args.action=='prepare':
            require(not output.exists(),'Manifest exists; refusing overwrite')
            proposals={}
            for method in METHODS:
                if args.site=='ordinary':
                    p=request(owner,'POST',root+'/proposals',expected=201,json={'title':f'Phase113 {method} choices','body':'Fictional release QA only','voting_method':method,'num_winners':2,'options':[{'label':n} for n in ('Rain garden','Library evening','Play corner')]})
                else:
                    p=request(owner,'POST',root+'/elections',expected=201,json={'title_id':fixture['titles'][args.site][method],'voting_method':method,'num_winners':2})
                pid=p['id'];proposals[method]=pid
                output.write_text(json.dumps(proposals,indent=2),encoding='utf-8')
                require(p['voting_rules']['method']==method and 'tie_seed' not in p['voting_rules'],'Protected rules exposed')
                if args.site!='ordinary':
                    for username in USERNAMES[1:]:request(clients[username],'POST',root+f'/elections/{pid}/candidacies',expected=201)
                while p['status']!='voting':
                    require(p['status'] in ('draft','deliberation'),'Unexpected lifecycle')
                    p=request(owner,'POST',f'/api/proposals/{pid}/advance',json={})
                payload=ballot(method,p['options'],None if args.site=='ordinary' else ids)
                request(clients[USERNAMES[3]],'POST',f'/api/proposals/{pid}/vote',json=payload)
                if args.site=='worker':request(owner,'POST',f'/api/proposals/{pid}/vote',json=payload)
                with httpx.Client(base_url=args.base_url,timeout=30) as public:
                    require(public.get(f'/api/proposals/{pid}/results').status_code in (401,403,404),'Private result leaked')
                    require(public.get(f'/api/proposals/{pid}/vote-graph').status_code in (401,403,404),'Private graph leaked')
            return {'prepared':proposals,'site':args.site,'public_privacy':'PASS'}
        proposals=json.loads(output.read_text(encoding='utf-8'));require(set(proposals)==set(METHODS),'Complete manifest required')
        result={}
        for method,pid in proposals.items():
            p=request(owner,'GET',f'/api/proposals/{pid}')
            require(p['author_id']==ids[USERNAMES[0]] and p['sub_org_id'] is None and p['num_winners']==2 and p['voting_method']==method,'Proposal outside fixture')
            require(p['is_election']==(args.site!='ordinary'),'Wrong proposal kind')
            if args.site!='ordinary':require(p['election_title_id']==fixture['titles'][args.site][method],'Wrong fixture title')
            require(p['status']=='passed','Chrome/scoped worker close required')
            if args.require_browser_ballots:
                vote=request(owner,'GET',f'/api/proposals/{pid}/my-vote');require(vote['is_direct'] is True,'Missing Chrome steward ballot')
            tally=request(owner,'GET',f'/api/proposals/{pid}/results');record=json.dumps(tally,sort_keys=True)
            mr=tally['method_result'];require(mr['finalized'] and mr['filled_count']=='2','Expected frozen whole set')
            payload=ballot(method,p['options'],None if args.site=='ordinary' else ids)
            expected={group[0] for group in payload['rank_groups']} if method=='ranked_pairs' else set(payload['grades' if method=='majority_judgment' else 'scores'])
            require(set(mr['winners'])==expected,'Wrong winner set')
            if args.site!='ordinary':require(set(mr['election']['winner_user_ids'])=={ids[u] for u in USERNAMES[1:3]} and mr['election']['installation']=='installed','Wrong office installation')
            require(json.dumps(request(owner,'GET',f'/api/proposals/{pid}/results'),sort_keys=True)==record,'Frozen retrieval changed')
            result[method]={'proposal_id':pid,'frozen':True,'filled_count':2,'office_installed':args.site!='ordinary'}
        return result
    finally:
        for c in clients.values():c.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','finish'));parser.add_argument('--base-url',required=True);parser.add_argument('--fixture',required=True);parser.add_argument('--credentials',required=True);parser.add_argument('--site',choices=('ordinary','manual','worker'),required=True);parser.add_argument('--output',required=True);parser.add_argument('--require-browser-ballots',action='store_true')
    print(json.dumps(run(parser.parse_args()),indent=2))
if __name__=='__main__':main()
