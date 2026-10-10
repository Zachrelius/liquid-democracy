import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { selectableVotingMethods, multiwinnerEnabled } from '../src/utils/votingMethods.js';
import { exactRational, displayRational } from '../src/utils/exactRational.js';
let server, Results, Ballot, Settings, History, Toast;
before(async()=>{
  server=await createServer({optimizeDeps:{noDiscovery:true,include:[]},cacheDir:'node_modules/.vite-phase113-allocated-tests',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  Results=(await server.ssrLoadModule('/src/components/ExperimentalResultsPanel.jsx')).default;
  Ballot=(await server.ssrLoadModule('/src/components/RatedBallot.jsx')).default;
  Settings=(await server.ssrLoadModule('/src/components/VotingMethodSettings.jsx')).default;
  History=(await server.ssrLoadModule('/src/components/MultiwinnerHistory.jsx')).default;
  Toast=(await server.ssrLoadModule('/src/components/Toast.jsx')).ToastProvider;
});
after(async()=>{await server?.close();});
const render=(component,props)=>renderToStaticMarkup(createElement(component,props));
const q=(n,d='1')=>({numerator:String(n),denominator:String(d)});
test('Allocated Score has an independent opt-in, organization scope and at least two winners',()=>{
  const settings={allowed_voting_methods:['binary','allocated_score'],allowed_multiwinner_methods:[]};
  for(const election of [false,true]){
    assert.deepEqual(selectableVotingMethods(settings,{hasOrg:true,election,numWinners:1}),['binary']);
    assert.deepEqual(selectableVotingMethods(settings,{hasOrg:true,election,numWinners:2}),['binary','allocated_score']);
    assert.deepEqual(selectableVotingMethods(settings,{hasOrg:false,election,numWinners:2}),['binary']);
  }
  assert.equal(multiwinnerEnabled(settings,'allocated_score'),true);
  assert.equal(multiwinnerEnabled(settings,'score'),false);
  assert.equal(multiwinnerEnabled({},'allocated_score'),false);
  const html=render(Settings,{allowed:settings.allowed_voting_methods,permittedAllocatedScore:false,onChange(){}});
  assert.match(html,/-allocated_score[^>]*disabled[^>]*checked/);
  assert.doesNotMatch(html,/Allow multiple winners for Allocated/);
});
test('Allocated ballot uses points and discloses proportional influence without a runoff',()=>{
  const html=render(Toast,{children:createElement(Ballot,{proposal:{voting_method:'allocated_score',num_winners:2,options:[{id:'a',label:'Ada'}]},myVote:{scores:{a:5},is_direct:true},emailVerified:true,onVoteChange(){}})});
  assert.match(html,/Your Allocated Score ballot/);assert.match(html,/No automatic runoff/);
  assert.match(html,/All-zero ballots count as participation and override delegation/);
  assert.match(html,/never changes your shares/);assert.doesNotMatch(html,/full weight in every round|two highest total scores reach a runoff|stars/);
});
test('allocation results show original quota, every aggregate round and support exhaustion',()=>{
  const r={winners:['a'],requested_count:'2',filled_count:'1',unfilled_count:'1',scores:{a:'150',b:'0'},option_labels:{a:'Ada',b:'Bea'},finalized:true,quorum_met:true,informative_weight:'30',quota:q(15),allocated_weight:q(15),remaining_weight:q(15),stop_reason:'no_remaining_positive_support',rounds:[{winner:'a',pool:['a','b'],totals:{a:q(150),b:q(0)},remaining_weight_before:q(30),allocated_weight:q(15),remaining_weight_after:q(15),quota_shortfall:q(0),allocation_bands:[{contribution:q(5),remaining_mass:q(30),allocated_mass:q(15),allocated_fraction:q(1,2)}]}]};
  const html=render(Results,{proposal:{voting_method:'allocated_score',voting_rules:{rule_id:'allocated_score_0_5_hare_v1'}},tally:{method_result:r}});
  assert.match(html,/Selected: Ada/);assert.match(html,/Fixed quota: 15/);assert.match(html,/1 unfilled/);
  assert.match(html,/Counting stopped on exhausted positive support/);assert.match(html,/common fraction allocated 1\/2/);
  assert.match(html,/Zero-contribution bands can be reached/);assert.match(html,/No automatic runoff/);
  assert.doesNotMatch(html,/Finalists|Runoff total|user_id|voter_id|profiles/);
});
test('large exact rationals retain all digits and rounded display never drives arithmetic',()=>{
  const n='1000000000000000000000000000000000000000000000000000000001';
  assert.equal(exactRational(q(n,3)),`${n}/3`);
  assert.match(displayRational(q(n,3)),/^≈ /);
  assert.equal(displayRational(q(1,3)),'≈ 0.33');assert.equal(displayRational(q(2,3)),'≈ 0.67');
  assert.equal(exactRational(q(1,0)),'Unavailable');
});
test('all five histories disclose a collective set and variant-specific deciding aggregates',()=>{
  for(const method of ['score','star','majority_judgment','ranked_pairs','allocated_score']){
    const r={winners:['a','b'],filled_count:'2',requested_count:'3',unfilled_count:'1',unfilled_reason:'support_exhausted',priority_used:true,scores:{a:'10',b:'8'},majority_grades:{a:'5',b:'4'},ranked_order:['a','b'],locked_edges:[{winner:'a',loser:'b'}],quota:q(5),allocated_weight:q(10),remaining_weight:q(5),rounds:method==='star'?[{winner:'a',competitive_runoff:true,runoff:{a:'3',b:'2'},equal_preference:'0'}]:method==='allocated_score'?[{winner:'a',allocated_weight:q(5),remaining_weight_after:q(10)}]:[]};
    const html=render(History,{method,optionsById:{a:{label:'Ada'},b:{label:'Bea'}},snapshots:[{id:1,captured_at:'2026-10-10T12:00:00Z',method_result:r}]});
    assert.match(html,/Ada, Bea/);assert.match(html,/2 of 3 selected/);assert.match(html,/Unfilled: 1/);assert.match(html,/Committed priority consulted/);
    if(method==='allocated_score')assert.match(html,/Fixed quota: 5.*No automatic runoff/s);
    if(method==='ranked_pairs')assert.match(html,/Collective order: Ada, Bea/);
    if(method==='majority_judgment')assert.match(html,/Ada: Excellent/);
    if(method==='star')assert.match(html,/Runoff: Ada 3; Bea 2/);
  }
});
