-- Create and save a parallel H10 Continuous Body Field project.
-- The currently open project is preserved in its own tab. This never
-- touches the V4 project tab or file.

local PROJECT_PATH = "/Users/taichengwong/Projects/H10/reaper_projects/H10 Continuous Body Field.RPP"
local H10_PORT = "H10 Continuous Body Field"
local MINILAB_PORT = "Arturia - Minilab3 - MIDI"

local function log(text)
  reaper.ShowConsoleMsg("[H10 Continuous setup] " .. text .. "\n")
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

local function fx_matches_expected(current_name, names)
  for _, name in ipairs(names) do
    if current_name == name then return true end
    -- names look like "JS: H10/Continuous/h10_continuous_heart"; also accept
    -- REAPER's display forms that embed the same distinguishing filename.
    local plain = name:gsub("^JS: ", "")
    if string.find(current_name, plain, 1, true) then return true end
  end
  return false
end

local function add_fx(track, names)
  if reaper.TrackFX_GetCount(track) > 0 then
    local _, current_name = reaper.TrackFX_GetFXName(track, 0, "")
    if fx_matches_expected(current_name, names) then return 0 end
    -- A track that already has an FX loaded is not necessarily the RIGHT
    -- FX -- e.g. a different rig's project (V4) can share this script's
    -- track-naming convention. Never silently keep a mismatched FX.
    log("WARNING: replacing mismatched FX '" .. current_name .. "' with the correct continuous FX")
    reaper.TrackFX_Delete(track, 0)
  end
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

local function active_project_is_unsaved_continuous()
  -- 7 tracks = pre-MELODY-VOICE Continuous layout, 8 = current layout.
  local count = reaper.CountTracks(0)
  if count ~= 7 and count ~= 8 then return false end
  local first = reaper.GetTrack(0, 0)
  local second = reaper.GetTrack(0, 1)
  local _, first_name = reaper.GetSetMediaTrackInfo_String(first, "P_NAME", "", false)
  local _, second_name = reaper.GetSetMediaTrackInfo_String(second, "P_NAME", "", false)
  if first_name ~= "H10 CONTROL" or second_name ~= "MINILAB CONTROL" then return false end
  -- H10 CONTROL / MINILAB CONTROL is also V4's track-naming convention, so
  -- name and count alone are not enough: only treat this as OUR half-built
  -- tab if it is unsaved, or already saved at OUR path. A V4 tab (or any
  -- other rig) saved somewhere else must never be mistaken for this one --
  -- this is exactly what caused the Continuous project to be a saved copy
  -- of the open V4 tab, complete with V4's JSFX, in an earlier run.
  local _, current_path = reaper.EnumProjects(-1, "")
  if current_path ~= "" and current_path ~= PROJECT_PATH then return false end
  return true
end

local function rebind_input(track, index, name, channel, label)
  if index then
    reaper.SetMediaTrackInfo_Value(track, "I_RECARM", 1)
    reaper.SetMediaTrackInfo_Value(track, "I_RECMON", 1)
    reaper.SetMediaTrackInfo_Value(track, "I_RECMODE", 0)
    reaper.SetMediaTrackInfo_Value(track, "I_RECINPUT", midi_input(index, channel))
    log(label .. " input bound to " .. name .. " index=" .. index)
  else
    log("WARNING: MIDI input for " .. label .. " not found; binding left unchanged")
  end
end

local function set_space_send_volume(source, space, volume)
  for send = 0, reaper.GetTrackNumSends(source, 0) - 1 do
    local destination = reaper.GetTrackSendInfo_Value(source, 0, send, "P_DESTTRACK")
    local midi_flags = reaper.GetTrackSendInfo_Value(source, 0, send, "I_MIDIFLAGS")
    if destination == space and midi_flags == 31 then
      reaper.SetTrackSendInfo_Value(source, 0, send, "D_VOL", volume)
      return
    end
  end
  -- No audio send to SPACE yet (e.g. healed from a foreign project state).
  audio_send(source, space, volume)
end

local function ensure_midi_send(source, destination)
  for send = 0, reaper.GetTrackNumSends(source, 0) - 1 do
    local dst = reaper.GetTrackSendInfo_Value(source, 0, send, "P_DESTTRACK")
    local midi_flags = reaper.GetTrackSendInfo_Value(source, 0, send, "I_MIDIFLAGS")
    if dst == destination and midi_flags == 0 then return end
  end
  midi_send(source, destination)
end

local MELODY_FX = {"JS: H10/Continuous/h10_continuous_melody_voice", "JS: H10 Continuous Melody Voice", "H10 Continuous Melody Voice"}

-- Idempotently create/repair the MELODY VOICE track (index 7): direct
-- MiniLab keyboard input (channel 2), the melody JSFX, an H10 CONTROL MIDI
-- send (bounded tint + CC123 panic/shutdown reach), and a deliberately
-- minimal long-tail send into SPACE so the melody stays foreground.
local function ensure_melody_voice(control, space, mini_index, mini_name)
  local melody
  if reaper.CountTracks(0) >= 8 then
    melody = reaper.GetTrack(0, 7)
    set_name(melody, "MELODY VOICE")
  else
    melody = add_track("MELODY VOICE", {181, 131, 77}, midi_input(mini_index, 0), 0.9, true)
  end
  set_color(melody, 181, 131, 77)
  reaper.SetMediaTrackInfo_Value(melody, "D_VOL", 0.9)
  reaper.SetMediaTrackInfo_Value(melody, "B_MAINSEND", 1)
  add_fx(melody, MELODY_FX)
  -- All channels, not a specific one: the MiniLab's own onboard channel
  -- assignment varies by which memory preset is active on the hardware
  -- (observed switching between MIDI channel 1, 2 and 10 across presets),
  -- and the JSFX itself now discriminates keyboard notes from the H10
  -- heartbeat by pitch (note 36 is always excluded), not by channel.
  rebind_input(melody, mini_index, mini_name, 0, "MELODY VOICE")
  ensure_midi_send(control, melody)
  set_space_send_volume(melody, space, 0.06)
  return melody
end

-- If the previous run built every track but failed only at the final save,
-- finish that save in-place instead of creating another project tab. Also
-- self-heals a tab that was previously mismatched (see guard above): renames
-- tracks, replaces any FX that isn't already the correct continuous one,
-- rebinds the control-track MIDI inputs (a healed V4 copy carries V4's
-- stale device number), and normalises the SPACE send hierarchy.
if active_project_is_unsaved_continuous() then
  reaper.Main_OnCommand(41175, 0) -- Reset MIDI devices so virtual ports refresh.
  set_name(reaper.GetTrack(0, 2), "HEART")
  set_name(reaper.GetTrack(0, 3), "EARTH")
  set_name(reaper.GetTrack(0, 4), "BODY")
  set_name(reaper.GetTrack(0, 5), "AIR")
  set_name(reaper.GetTrack(0, 6), "SPACE")
  add_fx(reaper.GetTrack(0, 2), {"JS: H10/Continuous/h10_continuous_heart", "JS: H10 Continuous Heart", "H10 Continuous Heart"})
  add_fx(reaper.GetTrack(0, 3), {"JS: H10/Continuous/h10_continuous_earth", "JS: H10 Continuous Earth", "H10 Continuous Earth"})
  add_fx(reaper.GetTrack(0, 4), {"JS: H10/Continuous/h10_continuous_body", "JS: H10 Continuous Body", "H10 Continuous Body"})
  add_fx(reaper.GetTrack(0, 5), {"JS: H10/Continuous/h10_continuous_air", "JS: H10 Continuous Air", "H10 Continuous Air"})
  add_fx(reaper.GetTrack(0, 6), {"JS: H10/Continuous/h10_continuous_space", "JS: H10 Continuous Space", "H10 Continuous Space"})
  add_fx(reaper.GetMasterTrack(0), {"JS: H10/Continuous/h10_continuous_master_guard", "JS: H10 Continuous Master Guard", "H10 Continuous Master Guard"})

  local h10_index, h10_name = find_midi_input(H10_PORT)
  local mini_index, mini_name = find_midi_input("Minilab3 - MIDI")
  if not mini_index then mini_index, mini_name = find_midi_input("Minilab3") end
  rebind_input(reaper.GetTrack(0, 0), h10_index, h10_name, 0, "H10 CONTROL")
  -- All channels: pads (ch3) for the bridge-parallel path plus knob/fader
  -- macro CCs (ch2), which the instrument JSFX read directly.
  rebind_input(reaper.GetTrack(0, 1), mini_index, mini_name, 0, "MINILAB CONTROL")

  local space = reaper.GetTrack(0, 6)
  set_space_send_volume(reaper.GetTrack(0, 2), space, 0.05)
  set_space_send_volume(reaper.GetTrack(0, 3), space, 0.15)
  set_space_send_volume(reaper.GetTrack(0, 4), space, 0.40)
  set_space_send_volume(reaper.GetTrack(0, 5), space, 0.65)

  ensure_melody_voice(reaper.GetTrack(0, 0), space, mini_index, mini_name)

  reaper.Main_SaveProjectEx(0, PROJECT_PATH, 8)
  log("Saved existing Continuous tab: " .. PROJECT_PATH)
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
else log("WARNING: start the continuous bridge, reset MIDI devices, then rerun setup to bind " .. H10_PORT) end
if mini_index then log("MiniLab input: " .. mini_name .. " index=" .. mini_index)
else log("WARNING: MiniLab MIDI input not found") end
if h10_index and midi_input_is_enabled(h10_index) == false then
  log("WARNING: enable " .. H10_PORT .. " in Preferences > Audio > MIDI Inputs")
end
if mini_index and midi_input_is_enabled(mini_index) == false then
  log("WARNING: enable " .. mini_name .. " in Preferences > Audio > MIDI Inputs")
end

local control = add_track("H10 CONTROL", {72, 145, 153}, midi_input(h10_index, 0), 0.0, false)
-- All channels: pads (ch3) plus knob/fader macro CCs (ch2).
local minilab = add_track("MINILAB CONTROL", {118, 91, 154}, midi_input(mini_index, 0), 0.0, false)
local heart = add_track("HEART", {184, 79, 75}, -1, 0.80, true)
local earth = add_track("EARTH", {79, 133, 101}, -1, 0.70, true)
local body = add_track("BODY", {76, 112, 166}, -1, 0.65, true)
local air = add_track("AIR", {153, 137, 92}, -1, 0.55, true)
local space = add_track("SPACE", {91, 82, 135}, -1, 0.60, true)

add_fx(heart, {"JS: H10/Continuous/h10_continuous_heart", "JS: H10 Continuous Heart", "H10 Continuous Heart"})
add_fx(earth, {"JS: H10/Continuous/h10_continuous_earth", "JS: H10 Continuous Earth", "H10 Continuous Earth"})
add_fx(body, {"JS: H10/Continuous/h10_continuous_body", "JS: H10 Continuous Body", "H10 Continuous Body"})
add_fx(air, {"JS: H10/Continuous/h10_continuous_air", "JS: H10 Continuous Air", "H10 Continuous Air"})
add_fx(space, {"JS: H10/Continuous/h10_continuous_space", "JS: H10 Continuous Space", "H10 Continuous Space"})

for _, destination in ipairs({heart, earth, body, air, space}) do
  midi_send(control, destination)
  midi_send(minilab, destination)
end

-- Default send hierarchy from the spec: HEART almost none, EARTH low,
-- BODY medium, AIR high. SPACE itself never sends to SPACE.
audio_send(heart, space, 0.05)
audio_send(earth, space, 0.15)
audio_send(body, space, 0.40)
audio_send(air, space, 0.65)

ensure_melody_voice(control, space, mini_index, mini_name)

local master = reaper.GetMasterTrack(0)
add_fx(master, {"JS: H10/Continuous/h10_continuous_master_guard", "JS: H10 Continuous Master Guard", "H10 Continuous Master Guard"})

reaper.PreventUIRefresh(-1)
reaper.TrackList_AdjustWindows(false)
reaper.UpdateArrange()
reaper.Undo_EndBlock("Create H10 Continuous Body Field project", -1)
reaper.Main_SaveProjectEx(0, PROJECT_PATH, 8)
log("Saved: " .. PROJECT_PATH)
log("Tracks: H10 CONTROL, MINILAB CONTROL, HEART, EARTH, BODY, AIR, SPACE, MELODY VOICE")
