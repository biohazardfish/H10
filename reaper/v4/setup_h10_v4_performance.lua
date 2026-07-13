-- Create and save a parallel H10 V4 live-performance project.
-- The currently open project is preserved in its own tab.

local PROJECT_PATH = "/Users/taichengwong/Projects/H10/reaper_projects/H10 Live Performance V4.RPP"
local H10_PORT = "H10 Performance V4"
local MINILAB_PORT = "Arturia - Minilab3 - MIDI"

local function log(text)
  reaper.ShowConsoleMsg("[H10 V4 setup] " .. text .. "\n")
end

local function find_midi_input(needle)
  local input_count = reaper.GetNumMIDIInputs and reaper.GetNumMIDIInputs() or 128
  for index = 0, input_count - 1 do
    local ok, name = reaper.GetMIDIInputName(index, "")
    if ok and name and string.find(string.lower(name), string.lower(needle), 1, true) then
      return index, name
    end
  end
  return nil, nil
end

local function midi_input_is_enabled(index)
  if not index or not reaper.get_config_var_string then return nil end
  local names = {"midiins", "midiins_h", "midiins_x", "midiins_x_h"}
  local group = math.floor(index / 32) + 1
  local name = names[group]
  if not name then return nil end
  local ok, value = reaper.get_config_var_string(name)
  if not ok then return nil end
  local mask = tonumber(value)
  if not mask then return nil end
  return (mask & (1 << (index % 32))) ~= 0
end

local function midi_input(device, channel)
  if not device then return -1 end
  return 4096 + device * 32 + channel
end

local function set_name(track, name)
  reaper.GetSetMediaTrackInfo_String(track, "P_NAME", name, true)
end

local function set_color(track, r, g, b)
  reaper.SetMediaTrackInfo_Value(track, "I_CUSTOMCOLOR", reaper.ColorToNative(r, g, b) | 0x1000000)
end

local function add_fx(track, names)
  if reaper.TrackFX_GetCount(track) > 0 then return 0 end
  for _, name in ipairs(names) do
    local index = reaper.TrackFX_AddByName(track, name, false, -1)
    if index >= 0 then
      log("Added " .. name)
      return index
    end
  end
  log("WARNING: FX not found: " .. table.concat(names, " | "))
  return -1
end

local function add_track(name, color, input, volume, main_send)
  local index = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(index, true)
  local track = reaper.GetTrack(0, index)
  set_name(track, name)
  set_color(track, color[1], color[2], color[3])
  reaper.SetMediaTrackInfo_Value(track, "D_VOL", volume or 1.0)
  reaper.SetMediaTrackInfo_Value(track, "B_MAINSEND", main_send == false and 0 or 1)
  if input and input >= 0 then
    reaper.SetMediaTrackInfo_Value(track, "I_RECARM", 1)
    reaper.SetMediaTrackInfo_Value(track, "I_RECMON", 1)
    reaper.SetMediaTrackInfo_Value(track, "I_RECMODE", 0)
    reaper.SetMediaTrackInfo_Value(track, "I_RECINPUT", input)
  end
  return track
end

local function midi_send(source, destination)
  local send = reaper.CreateTrackSend(source, destination)
  reaper.SetTrackSendInfo_Value(source, 0, send, "I_SRCCHAN", -1)
  reaper.SetTrackSendInfo_Value(source, 0, send, "I_MIDIFLAGS", 0)
end

local function audio_send(source, destination, volume)
  local send = reaper.CreateTrackSend(source, destination)
  reaper.SetTrackSendInfo_Value(source, 0, send, "D_VOL", volume)
  reaper.SetTrackSendInfo_Value(source, 0, send, "I_MIDIFLAGS", 31)
end

local function active_project_is_unsaved_v4()
  if reaper.CountTracks(0) ~= 7 then return false end
  local first = reaper.GetTrack(0, 0)
  local second = reaper.GetTrack(0, 1)
  local _, first_name = reaper.GetSetMediaTrackInfo_String(first, "P_NAME", "", false)
  local _, second_name = reaper.GetSetMediaTrackInfo_String(second, "P_NAME", "", false)
  return first_name == "H10 CONTROL" and second_name == "MINILAB CONTROL"
end

-- If the previous run built every track but failed only at the final save,
-- finish that save in-place instead of creating another project tab.
if active_project_is_unsaved_v4() then
  add_fx(reaper.GetTrack(0, 2), {"JS: H10/V4/h10_v4_heart", "JS: H10 V4 Heart", "H10 V4 Heart"})
  add_fx(reaper.GetTrack(0, 3), {"JS: H10/V4/h10_v4_earth_drone", "JS: H10 V4 Earth Drone", "H10 V4 Earth Drone"})
  add_fx(reaper.GetTrack(0, 4), {"JS: H10/V4/h10_v4_body_pad", "JS: H10 V4 Body Pad", "H10 V4 Body Pad"})
  add_fx(reaper.GetTrack(0, 5), {"JS: H10/V4/h10_v4_air_motion", "JS: H10 V4 Air Motion", "H10 V4 Air Motion"})
  add_fx(reaper.GetTrack(0, 6), {"JS: H10/V4/h10_v4_space_return", "JS: H10 V4 Space Return", "H10 V4 Space Return"})
  add_fx(reaper.GetMasterTrack(0), {"JS: H10/V4/h10_v4_master_guard", "JS: H10 V4 Master Guard", "H10 V4 Master Guard"})
  reaper.Main_SaveProjectEx(0, PROJECT_PATH, 8)
  log("Saved existing V4 tab: " .. PROJECT_PATH)
  return
end

reaper.Main_OnCommand(40859, 0) -- New project tab. Existing projects remain untouched.
reaper.Main_OnCommand(41175, 0) -- Reset MIDI devices so virtual ports refresh.
reaper.ClearConsole()
reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local h10_index, h10_name = find_midi_input(H10_PORT)
local mini_index, mini_name = find_midi_input("Minilab3 - MIDI")
if not mini_index then mini_index, mini_name = find_midi_input("Minilab3") end
if h10_index then log("H10 input: " .. h10_name .. " index=" .. h10_index)
else log("WARNING: start V4 bridge, reset MIDI devices, then rerun setup to bind " .. H10_PORT) end
if mini_index then log("MiniLab input: " .. mini_name .. " index=" .. mini_index)
else log("WARNING: MiniLab MIDI input not found") end
if h10_index and midi_input_is_enabled(h10_index) == false then
  log("WARNING: enable " .. H10_PORT .. " in Preferences > Audio > MIDI Inputs")
end
if mini_index and midi_input_is_enabled(mini_index) == false then
  log("WARNING: enable " .. mini_name .. " in Preferences > Audio > MIDI Inputs")
end

local control = add_track("H10 CONTROL", {72, 112, 153}, midi_input(h10_index, 0), 0.0, false)
local minilab = add_track("MINILAB CONTROL", {118, 91, 154}, midi_input(mini_index, 2), 0.0, false)
local heart = add_track("HEART", {184, 79, 75}, -1, 0.82, true)
local earth = add_track("EARTH DRONE", {79, 133, 101}, -1, 0.72, true)
local body = add_track("BODY PAD", {76, 112, 166}, -1, 0.65, true)
local air = add_track("AIR MOTION", {153, 137, 92}, -1, 0.55, true)
local space = add_track("SPACE RETURN", {91, 82, 135}, -1, 0.62, true)

add_fx(heart, {"JS: H10/V4/h10_v4_heart", "JS: H10 V4 Heart", "H10 V4 Heart"})
add_fx(earth, {"JS: H10/V4/h10_v4_earth_drone", "JS: H10 V4 Earth Drone", "H10 V4 Earth Drone"})
add_fx(body, {"JS: H10/V4/h10_v4_body_pad", "JS: H10 V4 Body Pad", "H10 V4 Body Pad"})
add_fx(air, {"JS: H10/V4/h10_v4_air_motion", "JS: H10 V4 Air Motion", "H10 V4 Air Motion"})
add_fx(space, {"JS: H10/V4/h10_v4_space_return", "JS: H10 V4 Space Return", "H10 V4 Space Return"})

for _, destination in ipairs({heart, earth, body, air, space}) do
  midi_send(control, destination)
  midi_send(minilab, destination)
end

audio_send(heart, space, 0.18)
audio_send(earth, space, 0.10)
audio_send(body, space, 0.42)
audio_send(air, space, 0.58)

local master = reaper.GetMasterTrack(0)
add_fx(master, {"JS: H10/V4/h10_v4_master_guard", "JS: H10 V4 Master Guard", "H10 V4 Master Guard"})

reaper.PreventUIRefresh(-1)
reaper.TrackList_AdjustWindows(false)
reaper.UpdateArrange()
reaper.Undo_EndBlock("Create H10 V4 live-performance project", -1)
reaper.Main_SaveProjectEx(0, PROJECT_PATH, 8)
log("Saved: " .. PROJECT_PATH)
log("Tracks: H10 CONTROL, MINILAB CONTROL, HEART, EARTH DRONE, BODY PAD, AIR MOTION, SPACE RETURN")
