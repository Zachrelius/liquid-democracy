import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { selectableVotingMethods, multiwinnerEnabled, draftWinnerCountResetFields } from '../src/utils/votingMethods.js';
import { experimentalElectionSummary } from '../src/utils/electionOutcome.js';
let server, Settings, Results, Ballot, Toast;
before(async () => {
  server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] },cacheDir:'node_modules/.vite-phase113-score-tests',server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  Settings=(await server.ssrLoadModule('/src/components/VotingMethodSettings.jsx')).default;
  Results=(await server.ssrLoadModule('/src/components/ExperimentalResultsPanel.jsx')).default;
  Ballot=(await server.ssrLoadModule('/src/components/RatedBallot.jsx')).default;
  Toast=(await server.ssrLoadModule('/src/components/Toast.jsx')).ToastProvider;
});
after(async()=>{await server?.close();});
const render=(component,props)=>renderToStaticMarkup(createElement(component,props));
test('multiwinner requires effective separate permission without enabling other variants',()=>{
  const settings={allowed_voting_methods:['score','star','ranked_choice'],allowed_multiwinner_methods:['score']};
  assert.deepEqual(selectableVotingMethods(settings,{hasOrg:true,election:true,numWinners:2}),['ranked_choice','score']);
  assert.deepEqual(selectableVotingMethods(settings,{hasOrg:false,numWinners:2}),['ranked_choice']);
  assert.equal(multiwinnerEnabled(settings,'score'),true);assert.equal(multiwinnerEnabled(settings,'star'),false);
});
test('draft count changes need explicit destructive confirmation; identical counts do not',()=>{
  assert.throws(()=>draftWinnerCountResetFields(1,2,true,false),/Confirm/);
  assert.deepEqual(draftWinnerCountResetFields(1,2,true,true),{confirm_ballot_reset:true});
  assert.deepEqual(draftWinnerCountResetFields(2,2,true,false),{});
});
test('separate opt-in is labeled, explains full influence and honors parent restriction',()=>{
  const html=render(Settings,{allowed:['binary','score'],multiwinner:[],permittedMultiwinner:[],onChange(){},onMultiwinnerChange(){}});
  assert.match(html,/Allow multiple winners for Score Voting/);assert.match(html,/does not provide proportional representation/);
  assert.match(html,/type="checkbox"[^>]*disabled.*Allow multiple winners/s);
  assert.match(html,/entire|selected set together/);
});
test('results show a set, boundary ties, unsupported tail and frozen seed accurately',()=>{
  const html=render(Results,{proposal:{voting_method:'score',voting_rules:{rule_id:'score_0_5_top_n_v1',tie_commitment:'commit'}},tally:{method_result:{requested_count:'2',filled_count:'1',unfilled_count:'1',winners:['a'],ranked_order:['a'],scores:{a:'12',b:'0'},option_labels:{a:'Ada',b:'Bea'},quorum_met:true,finalized:true,selection_boundary_tie:true,priority_used:true,tie_seed:'revealed'}}});
  assert.match(html,/Selected: Ada/);assert.match(html,/1 of 2 places/);assert.match(html,/unfilled/);assert.match(html,/Unsupported/);
  assert.match(html,/boundary/);assert.match(html,/Revealed seed: revealed/);assert.doesNotMatch(html,/Provisional leader/);
});
test('ballot states count and nonproportional rule before rating',()=>{
  const html=render(Toast,{children:createElement(Ballot,{proposal:{voting_method:'score',num_winners:2,options:[{id:'a',label:'Ada'}]},emailVerified:true,onVoteChange(){}})});
  assert.match(html,/Up to 2 selections/);assert.match(html,/full weight/);assert.match(html,/does not provide proportional representation/);
  assert.doesNotMatch(html,/The option with the highest total points wins/);
});
test('plural installed and rejected outcomes use only frozen names and full-set policy',()=>{
  const outcome={outcome_version:2,winner_user_ids:['a','b'],candidate_snapshot:{x:{user_id:'a',display_name:'Ada'},y:{user_id:'b',display_name:'Bea'}},selected_count:2,requested_count:2};
  assert.match(experimentalElectionSummary({...outcome,installation:'installed'}),/Ada, Bea.*2 of 2 places/);
  assert.match(experimentalElectionSummary({...outcome,installation:'pending_verification'}),/entire set.*no new office/);
  assert.match(experimentalElectionSummary({...outcome,installation:'rejected',reason:'capacity'}),/entire set.*preserved/);
});

test('Bloc STAR opt-in and results disclose unchanged influence and each runoff',()=>{
  const settings=render(Settings,{allowed:['binary','star'],multiwinner:['star'],onChange(){},onMultiwinnerChange(){}});
  assert.match(settings,/Allow Bloc STAR for multiple winners/);assert.match(settings,/full weight in every round/);
  const result={requested_count:'2',filled_count:'2',unfilled_count:'0',winners:['b','c'],ranked_order:['b','c'],scores:{a:'20',b:'31',c:'22'},option_labels:{a:'Ada',b:'Bea',c:'Cara'},quorum_met:true,finalized:true,rounds:[{winner:'b',pool:['a','b','c'],scores:{a:'20',b:'31',c:'22'},competitive_runoff:true,finalists:['b','c'],runoff:{b:'7',c:'2'},equal_preference:'0',tie_trace:[]},{winner:'c',pool:['a','c'],scores:{a:'20',c:'22'},competitive_runoff:true,finalists:['c','a'],runoff:{c:'5',a:'4'},equal_preference:'0',tie_trace:[]}]};
  const html=render(Results,{proposal:{voting_method:'star'},tally:{method_result:result}});
  assert.match(html,/Selected: Bea, Cara/);assert.match(html,/runoffs decide selections/);
  assert.match(html,/Round 1: Bea/);assert.match(html,/Round 2: Cara/);assert.match(html,/Cara 5; Ada 4/);
  assert.doesNotMatch(html,/Ranked total points/);
});


test('Majority Judgment top-N explains grade order and preserves original distributions',()=>{
  const settings=render(Settings,{allowed:['binary','majority_judgment'],multiwinner:['majority_judgment'],onChange(){},onMultiwinnerChange(){}});
  assert.match(settings,/Allow multiple winners for Majority Judgment/);
  const r={requested_count:'2',filled_count:'2',unfilled_count:'0',winners:['a','b'],ranked_order:['a','b','c'],supported_options:['a','b','c'],majority_grades:{a:'4',b:'4',c:'4',d:'0'},grade_histograms:{a:['0','0','1','1','2','1'],b:['0','1','0','1','2','1'],c:['1','0','0','1','2','1'],d:['5','0','0','0','0','0']},option_labels:{a:'Ada',b:'Bea',c:'Cara',d:'Dee'},quorum_met:true,finalized:true,selection_boundary_tie:true,comparisons:[{pool:['b','c'],winner:'b',tie_trace:[{stage:'median_removal',removed_per_candidate:'3',majority_grades:{b:'1',c:'0'}}]}]};
  const html=render(Results,{proposal:{voting_method:'majority_judgment'},tally:{method_result:r}});
  assert.match(html,/Selected: Ada, Bea/);assert.match(html,/Very good/);assert.match(html,/original distributions/);
  assert.match(html,/Temporary grades removed per candidate: 3/);assert.match(html,/Bea Poor; Cara Reject/);assert.match(html,/Unsupported/);
  assert.doesNotMatch(html,/Ranked total points|<th[^>]*>Points/);
});
