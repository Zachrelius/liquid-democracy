import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { optionLabelMap } from '../src/utils/optionDisplay.js';
import { experimentalElectionSummary as summary } from '../src/utils/electionOutcome.js';
import { experimentalOptionsLocked, selectableVotingMethods } from '../src/utils/votingMethods.js';
let server, Ballot, Groups, Toast;
before(async () => {
  server=await createServer({cacheDir:'node_modules/.vite-phase110-election-tests',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  Ballot=(await server.ssrLoadModule('/src/components/RatedBallot.jsx')).default;
  Groups=(await server.ssrLoadModule('/src/components/RankGroupsBallot.jsx')).default;
  Toast=(await server.ssrLoadModule('/src/components/Toast.jsx')).ToastProvider;
});
after(async()=>{await server?.close();});
const options=[{id:'a',label:'canonical-user-1',description:'Ada Example'},{id:'b',label:'canonical-user-2',description:'Bea Example'}];
test('all four saved election ballots show candidate names without losing identity keys',()=>{
  for(const method of ['star','score','majority_judgment','ranked_pairs']) {
    const vote=method==='ranked_pairs'?{rank_groups:[['b'],['a']],is_direct:true}:{[method==='majority_judgment'?'grades':'scores']:{a:0,b:5},is_direct:true};
    const html=renderToStaticMarkup(createElement(Toast,null,createElement(method==='ranked_pairs'?Groups:Ballot,{proposal:{is_election:true,voting_method:method,options},proposalId:'election',myVote:vote,emailVerified:true,onVoteChange(){}})));
    assert.match(html,/Ada Example/);assert.match(html,/Bea Example/);assert.doesNotMatch(html,/canonical-user-|write-ins/);
  }
});
test('frozen candidate names beat later name edits; legacy identity maps resolve display names',()=>{
  const p={is_election:true,options};
  assert.deepEqual(optionLabelMap(p,{a:'Ada at close',b:'Bea at close'}),{a:'Ada at close',b:'Bea at close'});
  assert.deepEqual(optionLabelMap(p,{a:'canonical-user-1'}),{a:'Ada Example',b:'Bea Example'});
});
test('announcements distinguish counting, installation, verification and holdover',()=>{
  const o={winner_user_id:'u',candidate_snapshot:{b:{user_id:'u',display_name:'Bea'}}};
  assert.match(summary({...o,installation:'installed'}),/Elected: Bea.*installation completed/);
  assert.match(summary({...o,installation:'pending_verification'}),/pending verification.*No bound-role access/);
  assert.match(summary({...o,installation:'rejected',reason:'capacity'}),/could not be installed.*preserved/);
  assert.match(summary({...o,installation:'installed',policy:'uncontested'}),/Uncontested election/);
  assert.match(summary({reason:'no_candidates'}),/no candidates.*no seats/);assert.match(summary({reason:'quorum_not_met'}),/Quorum not met/);
});
test('candidate write-in controls stay locked throughout the election lifecycle',()=>{
  for(const voting_method of ['star','score','ranked_pairs','majority_judgment']) {
    for(const status of ['draft','deliberation','voting','passed'])assert.equal(experimentalOptionsLocked({voting_method,status,is_election:true}),true);
    assert.equal(experimentalOptionsLocked({voting_method,status:'voting',is_election:false}),false);
  }
});
test('one-seat eligibility explicitly excludes methods from multiple-seat elections',()=>{
  const s={allowed_voting_methods:['ranked_choice','star','score','ranked_pairs','majority_judgment']};
  assert.deepEqual(selectableVotingMethods(s,{hasOrg:true,election:true,numWinners:1}),s.allowed_voting_methods);
  assert.deepEqual(selectableVotingMethods(s,{hasOrg:true,election:true,numWinners:2}),['ranked_choice']);
});
