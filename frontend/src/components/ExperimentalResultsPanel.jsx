import MajorityJudgmentResultsPanel from './MajorityJudgmentResultsPanel';
import RatedResultsPanel from './RatedResultsPanel';
import RankedPairsResultsPanel from './RankedPairsResultsPanel';

export default function ExperimentalResultsPanel(props) {
  if (props.proposal.voting_method === 'majority_judgment') return <MajorityJudgmentResultsPanel {...props} />;
  return props.proposal.voting_method === 'ranked_pairs'
    ? <RankedPairsResultsPanel {...props} /> : <RatedResultsPanel {...props} />;
}
