import RatedResultsPanel from './RatedResultsPanel';
import RankedPairsResultsPanel from './RankedPairsResultsPanel';

export default function ExperimentalResultsPanel(props) {
  return props.proposal.voting_method === 'ranked_pairs'
    ? <RankedPairsResultsPanel {...props} /> : <RatedResultsPanel {...props} />;
}
