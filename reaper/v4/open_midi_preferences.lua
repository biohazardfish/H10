-- Open REAPER's MIDI device preferences for the one-time input enable step.

if reaper.ViewPrefs then
  reaper.ViewPrefs(0, "MIDI Devices")
else
  reaper.Main_OnCommand(40016, 0) -- Options: Preferences
end
