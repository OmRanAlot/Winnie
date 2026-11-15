// Approved roster information is displayed without an application edit path.
export default function BoardInformation({ member }) {
  const list = values => values?.length ? values.join(', ') : 'Not provided';
  return <section className="panel">
    <p>Board information comes from the approved roster files and is read-only here.</p>
    <dl>
      <dt>Name</dt><dd>{member.name}</dd>
      <dt>Position</dt><dd>{member.role}</dd>
      <dt>Skills</dt><dd>{list(member.skills)}</dd>
      <dt>Previous roles</dt><dd>{list(member.previousRoles)}</dd>
      <dt>Skills from previous roles</dt><dd>{list(member.previousRoleSkills)}</dd>
    </dl>
  </section>;
}
