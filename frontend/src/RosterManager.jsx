// Administrator view for private contact details, board roles, and roster membership.
import { useEffect, useId, useRef, useState } from 'react';
import {
  addBoardMember, getBoardRoster, getMessagingContacts, syncMessagingContacts, updateBoardMember,
} from './lib/api.js';
import './RosterManager.css';

const BOARD_ROLES = [
  'President', 'Vice President', 'Treasurer', 'Secretary', 'Event Coordinator',
  'Industry Partnerships Chair', 'Community Outreach Chair', 'Membership Chair',
  'PR Chair', 'Technical Director',
];

function formValues(member) {
  return {
    display_name: member?.display_name ?? '',
    board_role: member?.board_role?.toLowerCase() === 'member' ? '' : member?.board_role ?? '',
    email: member?.email ?? '',
    phone_number: member?.phone_number ?? '',
    contact_consent: member?.contact_consent ?? false,
  };
}

function normalizeContact(row) {
  return {
    member_code: row.member_code,
    display_name: row.display_name,
    board_role: row.board_role,
    phone_number: row.phone_number,
    handle: row.handle,
    identity_linked: row.identity_linked,
    ready: row.ready,
    issue: row.errors?.length ? row.errors.join(' ') : row.issue,
  };
}

function RosterForm({ member, roles, self, busy, error, onSave, onClose, onViewProfile }) {
  const original = formValues(member);
  const [form, setForm] = useState(original);
  const [confirmation, confirm] = useState(null);
  const roleListId = useId();
  const contactHelpId = useId();
  const change = key => event => {
    const { type, checked, value } = event.target;
    setForm(previous => ({ ...previous, [key]: type === 'checkbox' ? checked : value }));
    confirm(null);
  };
  const normalized = {
    display_name: form.display_name.trim(),
    board_role: form.board_role.trim(),
    email: form.contact_consent ? form.email.trim().toLowerCase() : '',
    phone_number: form.contact_consent ? form.phone_number.trim() : '',
    contact_consent: form.contact_consent,
  };
  const patch = Object.fromEntries(Object.entries(normalized).filter(
    ([key, value]) => !member || original[key] !== value
  ));
  const emailChanged = Boolean(member?.email && 'email' in patch);
  const submit = event => {
    event.preventDefault();
    if (confirmation === 'remove' || !Object.keys(patch).length || !normalized.display_name) return;
    if (emailChanged && confirmation !== 'email') {
      confirm('email');
      return;
    }
    onSave(patch);
  };

  return <section className="panel roster-editor" aria-label={member ? 'Edit board member' : 'Add board member'}>
    <h3>{member ? `Edit ${member.display_name}` : 'Add board member'}</h3>
    <form onSubmit={submit}>
      <fieldset className="roster-fields" disabled={busy}>
        <label>Name <input className="field" autoFocus required maxLength={200} value={form.display_name}
          onChange={change('display_name')} autoComplete="off" /></label>
        <div className="roster-field">
          <label>Board role <input className="field" list={roleListId} maxLength={100}
            value={form.board_role} onChange={change('board_role')} placeholder="No role assigned" /></label>
          <datalist id={roleListId}>{roles.map(role => <option key={role} value={role} />)}</datalist>
          {form.board_role && <button type="button" className="link" onClick={() => {
            setForm(previous => ({ ...previous, board_role: '' }));
            confirm(null);
          }}>Clear role</button>}
        </div>
        <label className="roster-consent"><input type="checkbox" checked={form.contact_consent}
          onChange={change('contact_consent')} disabled={self} />
          This member gave permission to store their contact details.</label>
        <label>Email <input className="field" type="email" maxLength={254} value={form.email}
          onChange={change('email')} disabled={!form.contact_consent || self} autoComplete="off"
          aria-describedby={contactHelpId} /></label>
        <label>Phone number <input className="field" type="tel" maxLength={50} value={form.phone_number}
          onChange={change('phone_number')} disabled={!form.contact_consent} autoComplete="off" /></label>
        <small id={contactHelpId}>{self ? 'Ask another administrator to change your sign-in email.'
          : 'Email is used for sign-in and invitations. Phone numbers are stored as contact details.'}</small>
        {!form.contact_consent && (member?.email || member?.phone_number) &&
          <p className="roster-notice">Saving will clear this member’s email and phone number.</p>}
        {confirmation === 'email' && <p className="roster-notice" role="alert">
          Saving will revoke board access for the previous email. Review the new address before continuing.
        </p>}
        {confirmation === 'remove' && <p className="roster-notice" role="alert">
          Remove {member.display_name} from the active board? Their board access will be suspended and their history retained.
        </p>}
        {error && <p className="roster-notice" role="alert">{error}</p>}
        <div className="roster-actions">
          {confirmation === 'remove' ? <>
            <button type="button" className="btn" onClick={() => onSave({ active: false })}>Confirm removal</button>
            <button type="button" className="btn alt" onClick={() => confirm(null)}>Keep member</button>
          </> : <>
            <button type="submit" className="btn" disabled={!Object.keys(patch).length || !normalized.display_name}>
              {confirmation === 'email' ? 'Confirm email change' : member ? 'Save changes' : 'Add member'}
            </button>
            <button type="button" className="btn alt" onClick={onClose}>Cancel</button>
            {member?.active && onViewProfile && <button type="button" className="link"
              onClick={() => onViewProfile(member.code)}>View role and skills</button>}
            {member && !self && (member.active
              ? <button type="button" className="link" onClick={() => confirm('remove')}>Remove from board</button>
              : <button type="button" className="link" onClick={() => onSave({ active: true })}>Restore to board</button>)}
          </>}
        </div>
      </fieldset>
      {busy && <p role="status">Saving roster changes…</p>}
    </form>
  </section>;
}

export default function RosterManager({ currentMemberCode, onSaved, onViewProfile }) {
  const [members, setMembers] = useState(null);
  const [selected, select] = useState(null);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [contacts, setContacts] = useState(null);
  const [contactMeta, setContactMeta] = useState(null);
  const [contactError, setContactError] = useState('');
  const [syncingContacts, setSyncingContacts] = useState(false);
  const saving = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    getBoardRoster(controller.signal).then(rows => {
      if (!controller.signal.aborted) setMembers(rows);
    }).catch(cause => {
      if (!controller.signal.aborted) setError(cause.message);
    });
    getMessagingContacts(controller.signal).then(body => {
      if (controller.signal.aborted) return;
      setContacts((body.data || []).map(normalizeContact));
      setContactMeta(body.meta);
      setContactError('');
    }).catch(cause => {
      if (!controller.signal.aborted) setContactError(cause.message);
    });
    return () => controller.abort();
  }, [reload]);

  const choose = code => {
    select(code);
    setError('');
    setNotice('');
  };
  const member = members?.find(row => row.code === selected);
  const save = async fields => {
    if (saving.current) return;
    saving.current = true;
    setBusy(true);
    setError('');
    let saved;
    try {
      saved = member ? await updateBoardMember(member.code, fields) : await addBoardMember(fields);
      setMembers(previous => [...previous.filter(row => row.code !== saved.code), saved]
        .sort((left, right) => left.display_name.localeCompare(right.display_name)));
      select(null);
      setNotice(fields.active === false ? `${saved.display_name} was removed from the active board.`
        : fields.active === true ? `${saved.display_name} was restored to the board.`
          : member ? `Changes saved for ${saved.display_name}.` : `${saved.display_name} was added to the board.`);
    } catch (cause) {
      setError(cause.message);
    } finally {
      saving.current = false;
      setBusy(false);
    }
    if (saved) {
      try { await onSaved?.(); }
      catch { setNotice('Roster saved. Refresh the dashboard to see the latest board information.'); }
    }
  };

  if (!members) return error
    ? <p role="alert">{error} <button type="button" className="btn alt" onClick={() => {
      setError('');
      setReload(previous => previous + 1);
    }}>Retry</button></p>
    : <p role="status">Loading the board roster…</p>;

  const roles = [...new Set([...BOARD_ROLES, ...members.map(row => formValues(row).board_role).filter(Boolean)])]
    .sort((left, right) => left.localeCompare(right));
  const active = members.filter(row => row.active);
  const former = members.filter(row => !row.active);
  const entries = rows => <ul className="roster-entries">{rows.map(row => <li key={row.code}>
    <button type="button" className="pill" onClick={() => choose(row.code)} disabled={busy}
      aria-pressed={selected === row.code}>
      <strong>{row.display_name}</strong> <span>{formValues(row).board_role || 'No role assigned'}</span>
    </button>
  </li>)}</ul>;

  const syncPhones = async () => {
    if (syncingContacts) return;
    setSyncingContacts(true);
    setContactError('');
    try {
      const body = await syncMessagingContacts({ enrollPhoton: true, rotateAcrossLines: true });
      setContacts((body.data.contacts || []).map(normalizeContact));
      setContactMeta({
        total: body.meta.total,
        ready: body.meta.ready,
        with_phone: body.data.contacts.filter(row => row.handle).length,
        mode: body.meta.mode,
        lines: body.meta.lines,
      });
      const lineNote = body.meta.mode === 'dedicated' && body.meta.lines?.length
        ? ` Enrolled across ${body.meta.lines.length} Photon line${body.meta.lines.length === 1 ? '' : 's'} for rotation.`
        : '';
      setNotice(`Board phones synced: ${body.meta.ready} ready of ${body.meta.total}.${lineNote}`);
    } catch (cause) {
      setContactError(cause.message);
    } finally {
      setSyncingContacts(false);
    }
  };

  return <>
    {notice && <p className="roster-feedback" role="status">{notice}</p>}
    <section className="panel roster-phones" aria-label="Board phone numbers">
      <div className="roster-heading">
        <h3>Board phones for iMessage</h3>
        <button type="button" className="btn" disabled={syncingContacts || busy} onClick={syncPhones}>
          {syncingContacts ? 'Syncing…' : 'Sync all phones'}
        </button>
      </div>
      <p className="roster-phone-help">
        Keeps every consented e-board number available at once: links iMessage identities and enrolls
        Photon users. On dedicated Photon projects, each number is enrolled on every line so outbound
        texts can rotate across lines.
      </p>
      {contactError && <p className="roster-notice" role="alert">{contactError}</p>}
      {contactMeta && <p role="status">
        {contactMeta.ready || 0} ready · {contactMeta.with_phone || contacts?.length || 0} with usable phones
        {contactMeta.mode ? ` · Photon ${contactMeta.mode}` : ''}
        {contactMeta.lines?.length ? ` · ${contactMeta.lines.length} line${contactMeta.lines.length === 1 ? '' : 's'}` : ''}
      </p>}
      {!contacts ? <p role="status">Loading board phones…</p> : contacts.length ? (
        <ul className="roster-phone-list">
          {contacts.map(row => (
            <li key={`${row.member_code}-${row.handle || row.phone_number || 'missing'}`}>
              <strong>{row.display_name}</strong>
              <span>{row.handle || row.phone_number || 'No phone'}</span>
              <span className={row.ready ? 'roster-phone-ready' : 'roster-phone-pending'}>
                {row.ready ? 'Ready' : (row.issue || 'Needs sync')}
              </span>
            </li>
          ))}
        </ul>
      ) : <p>Add consented phone numbers on member records, then sync.</p>}
    </section>
    <div className="roster-layout">
      <section className="panel roster-directory" aria-label="Board roster">
        <div className="roster-heading">
          <h3>Active members</h3>
          <button type="button" className="btn" disabled={busy} onClick={() => choose('new')}>Add person</button>
        </div>
        {active.length ? entries(active) : <p>No active members.</p>}
        {former.length > 0 && <details>
          <summary>Former members ({former.length})</summary>
          {entries(former)}
        </details>}
      </section>
      {selected && <RosterForm key={selected} member={member} roles={roles} busy={busy} error={error}
        self={Boolean(member && member.code === currentMemberCode)} onSave={save}
        onClose={() => choose(null)} onViewProfile={onViewProfile} />}
    </div>
  </>;
}
