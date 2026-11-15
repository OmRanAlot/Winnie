// Verify form interactions persist through API helpers and expose failures honestly.
import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
const api = vi.hoisted(() => ({ edit: vi.fn(), get: vi.fn(), save: vi.fn(), ingest: vi.fn() }));
vi.mock('../src/lib/api.js', () => ({ editMember: api.edit, getEvaluation: api.get,
  saveEvaluation: api.save, ingestMeetingAudio: api.ingest }));
import ProfileEditor from '../src/ProfileEditor.jsx';
import EvaluationPanel from '../src/EvaluationPanel.jsx';
import UploadMeeting from '../src/UploadMeeting.jsx';
const member = {id:'A',name:'Alice',role:'Treasurer',skills:['Role-derived suggestion'],personalSkills:[],previousRoles:['Secretary']};
beforeEach(()=>{ vi.resetAllMocks(); api.edit.mockResolvedValue({}); api.get.mockResolvedValue({comments:'Stored feedback'});
  api.save.mockResolvedValue({}); api.ingest.mockResolvedValue({}); });
afterEach(cleanup);

it('approved roster information is readable without profile edit controls or writes', ()=>{
  render(<ProfileEditor member={member} />);
  expect(screen.getByText('Alice')).toBeTruthy();
  expect(screen.getByText('Treasurer')).toBeTruthy();
  expect(screen.getByText(/approved roster files/)).toBeTruthy();
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(screen.queryByRole('button')).toBeNull();
  expect(api.edit).not.toHaveBeenCalled();
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
