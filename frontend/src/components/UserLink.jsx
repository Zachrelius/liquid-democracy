import { Link } from 'react-router-dom';

/**
 * Renders a user's display name as a clickable link to their profile.
 * Accepts either a `user` object ({ id, display_name }) or individual props.
 */
export default function UserLink({ user, userId, displayName, className = '' }) {
  const id = user?.id ?? userId;
  const name = user?.display_name ?? displayName;
  if (!id || !name) return <span className={className}>{name || 'Unknown'}</span>;
  return (
    <Link
      to={`/users/${id}`}
      className={`text-[#2E75B6] hover:underline font-medium ${className}`}
    >
      {name}
    </Link>
  );
}
