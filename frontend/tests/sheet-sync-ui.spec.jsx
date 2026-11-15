// Admin preview and explicit apply, including provider failure and conflict handling.
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SheetSync from '../src/SheetSync.jsx';
import { applySheetSync, getSheetSyncSources, previewSheetSync } from '../src/lib/api.js';

vi.mock('../src/lib/api.js', () => ({
  getAutomationStatus: vi.fn().mockResolvedValue({jobs:[],notifications:{}}), applySheetSync: vi.fn(), getSheetSyncSources: vi.fn(), previewSheetSync: vi.fn(),
}));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const source = {key:'fall-board',spreadsheet_id:'demo',semester_code:'fall-2026',tab_id:7};
const plan = {plan_id:'a'.repeat(64),summary:{insert:1,update:0,unchanged:0},
  operations:[{action:'insert',source_task_id:'FALL26-001',values:{title:'Book room'}}],
  preserved:[],missing_from_sheet:[],conflicts:[]};

it('only writes after preview and an explicit apply click', async () => {
  getSheetSyncSources.mockResolvedValue([source]);
  previewSheetSync.mockResolvedValue(plan);
  applySheetSync.mockResolvedValue(plan.summary);
  const onApplied = vi.fn();
  render(<SheetSync onApplied={onApplied} />);
  fireEvent.click(await screen.findByText('Build Preview'));
  await screen.findByText('Changes');
  expect(applySheetSync).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('Apply Reviewed Changes'));
  await waitFor(() => expect(applySheetSync).toHaveBeenCalledWith('fall-board',plan.plan_id,{}));
  await waitFor(() => expect(onApplied).toHaveBeenCalled());
});

it('blocks unresolved conflicts and rebuilds with the chosen value', async () => {
  getSheetSyncSources.mockResolvedValue([source]);
  previewSheetSync.mockResolvedValue({...plan,conflicts:[{key:'FALL26-001:status',
    source_task_id:'FALL26-001',field:'status',winnie:'done',sheet:'todo'}]});
  render(<SheetSync />);
  fireEvent.click(await screen.findByText('Build Preview'));
  await screen.findByText('Conflicting edits');
  expect(screen.getByText('Apply Reviewed Changes').disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Keep value'),{target:{value:'winnie'}});
  fireEvent.click(screen.getByText('Build Preview'));
  await waitFor(() => expect(previewSheetSync).toHaveBeenLastCalledWith('fall-board',{'FALL26-001:status':'winnie'}));
});

it('shows Google access errors without claiming a save', async () => {
  getSheetSyncSources.mockResolvedValue([source]);
  previewSheetSync.mockRejectedValue(new Error('Google access was denied'));
  render(<SheetSync />);
  fireEvent.click(await screen.findByText('Build Preview'));
  expect((await screen.findByRole('alert')).textContent).toContain('Google access was denied');
  expect(applySheetSync).not.toHaveBeenCalled();
});
