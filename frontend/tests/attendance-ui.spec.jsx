// Exercise the attendance editor against mocked HTTP calls, including failed saves.
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Attendance from '../src/Attendance.jsx';
import { saveAttendance, createMeeting } from '../src/lib/api.js';

vi.mock('../src/lib/api.js', () => ({ saveAttendance: vi.fn(), createMeeting: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const meetings = [{ id: 1, name: 'Board', date: '9/3/2026', attendees: ['A'], attendance_recorded_at: 'saved' },
  { id: 2, name: 'Board', date: '9/10/2026', attendees: [] }];
const members = [{ id: 'A', name: 'Alice', role: 'Secretary' }, { id: 'B', name: 'Bob', role: 'Treasurer' }];

it('saves selected member codes and reports failure without marking data as saved', async () => {
  const onSaved = vi.fn();
  render(<Attendance meetings={meetings} members={members} onSaved={onSaved} />);
  fireEvent.click(screen.getByLabelText(/Bob/));
  saveAttendance.mockRejectedValueOnce(new Error('Storage unavailable'));
  fireEvent.click(screen.getByText('Save Attendance'));
  await screen.findByRole('alert');
  expect(onSaved).not.toHaveBeenCalled();
  expect(screen.getByLabelText(/Bob/).checked).toBe(true);
  saveAttendance.mockResolvedValueOnce({ attendees: ['A', 'B'] });
  fireEvent.click(screen.getByText('Save Attendance'));
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(1, ['A', 'B']));
});

it('switches meetings without copying an unsaved selection', () => {
  render(<Attendance meetings={meetings} members={members} />);
  fireEvent.click(screen.getByLabelText(/Bob/));
  fireEvent.change(screen.getByRole('combobox'), { target: { value: '2' } });
  expect(screen.getByLabelText(/Alice/).checked).toBe(false);
  expect(screen.getByLabelText(/Bob/).checked).toBe(false);
  expect(screen.getByText('Attendance has not been recorded yet.')).toBeTruthy();
});

it('creates attendance-only meetings with an explicit date', async () => {
  const onReload = vi.fn().mockResolvedValue();
  createMeeting.mockResolvedValue({ id: 3 });
  render(<Attendance meetings={[]} members={members} onReload={onReload} />);
  fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-11-14' } });
  fireEvent.click(screen.getByText('Add Meeting'));
  await waitFor(() => expect(createMeeting).toHaveBeenCalledWith('E-Board Meeting', '2026-11-14'));
  await waitFor(() => expect(onReload).toHaveBeenCalled());
});
