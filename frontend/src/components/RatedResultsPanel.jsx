import StarResultsPanel from './StarResultsPanel';
import ScoreResultsPanel from './ScoreResultsPanel';

export default function RatedResultsPanel(props) {
  return props.proposal.voting_method === 'score'
    ? <ScoreResultsPanel {...props} /> : <StarResultsPanel {...props} />;
}
