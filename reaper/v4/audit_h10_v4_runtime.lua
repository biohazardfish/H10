-- One-shot runtime audit for the H10 V4 project.
-- Run while the demo or live bridge is active; results are written to /tmp.

local output_path = "/tmp/h10_v4_runtime_audit.txt"
local lines = {}

local function add(line)
  lines[#lines + 1] = line
end

local _, project_path = reaper.EnumProjects(-1, "")
add(string.format("project=%s", project_path ~= "" and project_path or "[unsaved]"))
add(string.format("tracks=%d", reaper.CountTracks(0)))
if reaper.GetNumMIDIInputs and reaper.GetMIDIInputName then
  add(string.format("midi_inputs=%d", reaper.GetNumMIDIInputs()))
  for device = 0, reaper.GetNumMIDIInputs() - 1 do
    local ok, device_name = reaper.GetMIDIInputName(device, "")
    if ok then
      add(string.format("   MIDI IN %d name=%s", device, device_name))
    end
  end
end

for index = 0, reaper.CountTracks(0) - 1 do
  local track = reaper.GetTrack(0, index)
  local _, name = reaper.GetTrackName(track)
  local left = reaper.Track_GetPeakInfo(track, 0)
  local right = reaper.Track_GetPeakInfo(track, 1)
  local armed = reaper.GetMediaTrackInfo_Value(track, "I_RECARM")
  local input = reaper.GetMediaTrackInfo_Value(track, "I_RECINPUT")
  add(string.format(
    "%02d %-18s peak_l=%.6f peak_r=%.6f armed=%d input=%d",
    index + 1,
    name,
    left,
    right,
    armed,
    input
  ))
  for fx = 0, reaper.TrackFX_GetCount(track) - 1 do
    local _, fx_name = reaper.TrackFX_GetFXName(track, fx, "")
    add(string.format(
      "   FX %d name=%s enabled=%s offline=%s",
      fx + 1,
      fx_name,
      tostring(reaper.TrackFX_GetEnabled(track, fx)),
      tostring(reaper.TrackFX_GetOffline(track, fx))
    ))
  end
end

local master = reaper.GetMasterTrack(0)
add(string.format(
  "MASTER peak_l=%.6f peak_r=%.6f",
  reaper.Track_GetPeakInfo(master, 0),
  reaper.Track_GetPeakInfo(master, 1)
))
for fx = 0, reaper.TrackFX_GetCount(master) - 1 do
  local _, fx_name = reaper.TrackFX_GetFXName(master, fx, "")
  add(string.format(
    "   FX %d name=%s enabled=%s offline=%s",
    fx + 1,
    fx_name,
    tostring(reaper.TrackFX_GetEnabled(master, fx)),
    tostring(reaper.TrackFX_GetOffline(master, fx))
  ))
end

local file, err = io.open(output_path, "w")
if not file then
  reaper.ShowConsoleMsg("[H10 V4 audit] " .. tostring(err) .. "\n")
  return
end
file:write(table.concat(lines, "\n"), "\n")
file:close()
reaper.ShowConsoleMsg("[H10 V4 audit] wrote " .. output_path .. "\n")
