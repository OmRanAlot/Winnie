// Verify form interactions persist through API helpers and expose failures honestly.
import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
const api = vi.hoisted(() => ({ roster: vi.fn(), add: vi.fn(), edit: vi.fn(),
  contacts: vi.fn(), syncContacts: vi.fn(), get: vi.fn(), save: vi.fn(), ingest: vi.fn(), automation: vi.fn() }));
vi.mock('../src/lib/api.js', () => ({ getBoardRoster: api.roster, addBoardMember: api.add,
  updateBoardMember: api.edit, getMessagingContacts: api.contacts, syncMessagingContacts: api.syncContacts, getEvaluation: api.get,
  saveEvaluation: api.save, ingestMeetingAudio: api.ingest, getAutomationStatus: api.automation }));
import RosterManager from '../src/RosterManager.jsx';
import EvaluationPanel from '../src/EvaluationPanel.jsx';
import UploadMeeting from '../src/UploadMeeting.jsx';
import AutomationStatus from '../src/AutomationStatus.jsx';
const member = {id:'A',name:'Alice',role:'Treasurer',skills:['Role-derived suggestion'],personalSkills:[],previousRoles:['Secretary']};
const rosterMember = {code:'A', display_name:'Alice', board_role:'Treasurer', email:'alice@example.com',
  phone_number:null, contact_consent:true, active:true};
beforeEach(()=>{ vi.resetAllMocks(); api.roster.mockResolvedValue([rosterMember]);
  api.contacts.mockResolvedValue({data:[], meta:{total:0, ready:0, with_phone:0}});
  api.add.mockImplementation(async fields => ({...fields, code:'B', active:true}));
  api.edit.mockImplementation(async (_, fields) => ({...rosterMember, ...fields}));
  api.get.mockResolvedValue({comments:'Stored feedback'});
  api.save.mockResolvedValue({}); api.ingest.mockResolvedValue({}); });
afterEach(cleanup);

it('adds a person with contact consent, a shared role, and normalized email', async () => {
  const refresh = vi.fn();
  render(<RosterManager currentMemberCode="A" onSaved={refresh} />);
  fireEvent.click(await screen.findByRole('button', {name:'Add person'}));
  expect(screen.getByLabelText('Email').disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Name'), {target:{value:'  Bob Sample  '}});
  fireEvent.change(screen.getByLabelText('Board role'), {target:{value:'Treasurer'}});
  fireEvent.click(screen.getByLabelText(/gave permission/));
  fireEvent.change(screen.getByLabelText('Email'), {target:{value:'BOB@example.com'}});
  fireEvent.change(screen.getByLabelText('Phone number'), {target:{value:'(202) 555-0123'}});
  fireEvent.click(screen.getByRole('button', {name:'Add member'}));
  expect(await screen.findByRole('button', {name:'Bob Sample Treasurer'})).toBeTruthy();
  expect(api.add).toHaveBeenCalledWith({display_name:'Bob Sample', board_role:'Treasurer',
    email:'bob@example.com', phone_number:'(202) 555-0123', contact_consent:true});
  expect(refresh).toHaveBeenCalledOnce();
});

it('clears a role and removes or restores a member with their stable code', async () => {
  render(<RosterManager currentMemberCode="ADMIN" />);
  fireEvent.click(await screen.findByRole('button', {name:'Alice Treasurer'}));
  fireEvent.click(screen.getByRole('button', {name:'Clear role'}));
  fireEvent.click(screen.getByRole('button', {name:'Save changes'}));
  expect(api.edit).toHaveBeenLastCalledWith('A', {board_role:''});
  fireEvent.click(await screen.findByRole('button', {name:'Alice No role assigned'}));
  fireEvent.click(screen.getByRole('button', {name:'Remove from board'}));
  expect(api.edit).toHaveBeenCalledTimes(1);
  api.edit.mockResolvedValueOnce({...rosterMember, board_role:'member', active:false});
  fireEvent.click(screen.getByRole('button', {name:'Confirm removal'}));
  expect(await screen.findByText('Former members (1)')).toBeTruthy();
  expect(api.edit).toHaveBeenLastCalledWith('A', {active:false});
  fireEvent.click(screen.getByText('Former members (1)'));
  fireEvent.click(screen.getByText('Alice'));
  fireEvent.click(screen.getByRole('button', {name:'Restore to board'}));
  expect(api.edit).toHaveBeenLastCalledWith('A', {active:true});
  expect(await screen.findByText('Alice was restored to the board.')).toBeTruthy();
});

it('confirms email replacements and keeps edits visible if saving fails', async () => {
  api.edit.mockRejectedValueOnce(new Error('That email is already linked to another member.'));
  render(<RosterManager currentMemberCode="ADMIN" />);
  fireEvent.click(await screen.findByRole('button', {name:'Alice Treasurer'}));
  fireEvent.change(screen.getByLabelText('Email'), {target:{value:'replacement@example.com'}});
  fireEvent.click(screen.getByRole('button', {name:'Save changes'}));
  expect(api.edit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', {name:'Confirm email change'}));
  expect(await screen.findByText('That email is already linked to another member.')).toBeTruthy();
  expect(screen.getByLabelText('Email').value).toBe('replacement@example.com');
});

it('evaluation loads saved feedback, derives real counts, and persists edits',async()=>{
  render(<EvaluationPanel member={member} tasks={[]} meetings={[]} requests={[]} />);
  const input=await screen.findByDisplayValue('Stored feedback');
  expect(screen.getByText('0 of 0 assigned tasks completed')).toBeTruthy();
  fireEvent.change(input,{target:{value:'Updated feedback'}});
  fireEvent.click(screen.getByRole('button',{name:'Save evaluation'}));
  expect(await screen.findByText('Evaluation feedback saved.')).toBeTruthy();
  expect(api.save).toHaveBeenCalledWith('A','Updated feedback');
});

it('audio upload processes the selected file and refreshes stored meeting/task data',async()=>{
  const refresh=vi.fn().mockResolvedValue(); render(<UploadMeeting onSaved={refresh} />);
  const file=new File(['audio'],'meeting.wav',{type:'audio/wav'});
  fireEvent.change(screen.getByLabelText('Audio file'),{target:{files:[file]}});
  fireEvent.click(screen.getByRole('button',{name:'Upload and process'}));
  expect(await screen.findByText(/Meeting processed and saved/)).toBeTruthy();
  expect(api.ingest).toHaveBeenCalledWith(file,'Board meeting'); expect(refresh).toHaveBeenCalledOnce();
});

it('automation failures remain visible and retry reports pending/conflicted jobs without claiming delivery',async()=>{
  api.automation.mockRejectedValueOnce(new Error('Status unavailable')).mockResolvedValue({
    photon_enabled:true,notifications_enabled:true,reminders_enabled:true,scheduler_configured:true,
    jobs:[{key:'sheets:board',status:'conflict',started_at:'2026-11-15T14:00:00Z'}],
    notifications:{task_notifications:{pending:2,uncertain:1}},
  });
  render(<AutomationStatus />);
  expect(await screen.findByRole('alert')).toHaveProperty('textContent','Status unavailable');
  fireEvent.click(screen.getByRole('button',{name:'Refresh automation status'}));
  expect(await screen.findByText(/2 pending notifications/)).toBeTruthy();
  expect(screen.getByText(/review conflicting changes/)).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
});
