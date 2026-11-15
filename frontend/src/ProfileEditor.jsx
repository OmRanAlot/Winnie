import { getRoleProfile } from "./lib/roleProfiles.js";

// Approved roster information is displayed without an application edit path.
export default function BoardInformation({ member }) {
  const values = (items) => Array.isArray(items) ? items.filter(Boolean) : [];
  const skills = values(member.skills);
  const previousRoles = values(member.previousRoles);
  const previousRoleSkills = values(member.previousRoleSkills);
  const profile = getRoleProfile(member.role);

  return <section className="board-profile">
    <p className="board-profile-intro">Board information comes from the approved roster files and is read-only here.</p>
    <div className="board-profile-identity">
      <div className="board-profile-avatar" aria-hidden="true">{member.name?.split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase()}</div>
      <div><p className="board-profile-label">E-Board Member</p><h2>{member.name}</h2><p className="board-profile-role">{member.role}</p></div>
    </div>
    <div className="board-profile-sections">
      {profile && <section className="board-profile-card board-profile-card-wide">
        <h3>Role Overview</h3>
        <p className="board-profile-summary">{profile.summary}</p>
        {profile.responsibilities.length > 0 && <><h4>Key Responsibilities</h4>
          <ul className="board-profile-responsibilities">{profile.responsibilities.map((item) => <li key={item}>{item}</li>)}</ul></>}
      </section>}
      <section className="board-profile-card">
        <h3>Skills</h3>
        {skills.length ? <ul className="board-profile-tags">{skills.map((skill) => <li key={skill}>{skill}</li>)}</ul> : <p className="board-profile-empty">No skills recorded.</p>}
      </section>
      <section className="board-profile-card">
        <h3>Previous Roles</h3>
        {previousRoles.length ? <ul className="board-profile-list">{previousRoles.map((role) => <li key={role}>{role}</li>)}</ul> : <p className="board-profile-empty">No previous roles recorded.</p>}
      </section>
      <section className="board-profile-card board-profile-card-wide">
        <h3>Skills from Previous Roles</h3>
        {previousRoleSkills.length ? <ul className="board-profile-tags">{previousRoleSkills.map((skill) => <li key={skill}>{skill}</li>)}</ul> : <p className="board-profile-empty">No previous-role skills recorded.</p>}
      </section>
    </div>
  </section>;
}
