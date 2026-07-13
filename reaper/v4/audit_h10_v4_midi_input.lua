-- Short, self-cleaning MIDI input audit for H10 Performance V4.
-- Records the H10 CONTROL input for five seconds, reports event counts, then
-- removes the temporary item so the project arrangement is left unchanged.

local output_path = "/tmp/h10_v4_midi_input_audit.txt"
local track = reaper.GetTrack(0, 0)
if not track then return end

local initial_items = reaper.CountTrackMediaItems(track)
local started = reaper.time_precise()

reaper.SetMediaTrackInfo_Value(track, "I_RECARM", 1)
reaper.Main_OnCommand(1013, 0) -- Transport: Record

local stopped_at = nil

local function inspect_and_cleanup()
  -- REAPER finalizes recorded takes asynchronously after Transport: Stop.
  if reaper.time_precise() - stopped_at < 0.25 then
    reaper.defer(inspect_and_cleanup)
    return
  end
  local notes, ccs, sysex = 0, 0, 0
  local note36, cc119 = 0, 0
  local current_items = reaper.CountTrackMediaItems(track)

  for item_index = initial_items, current_items - 1 do
    local item = reaper.GetTrackMediaItem(track, item_index)
    local take = reaper.GetActiveTake(item)
    if take and reaper.TakeIsMIDI(take) then
      local _, take_notes, take_ccs, take_sysex = reaper.MIDI_CountEvts(take)
      notes = notes + take_notes
      ccs = ccs + take_ccs
      sysex = sysex + take_sysex

      for note_index = 0, take_notes - 1 do
        local ok, _, _, _, _, _, pitch = reaper.MIDI_GetNote(take, note_index)
        if ok and pitch == 36 then note36 = note36 + 1 end
      end
      for cc_index = 0, take_ccs - 1 do
        local ok, _, _, _, chanmsg, _, msg2 = reaper.MIDI_GetCC(take, cc_index)
        if ok and chanmsg == 176 and msg2 == 119 then cc119 = cc119 + 1 end
      end
    end
  end

  local file = io.open(output_path, "w")
  if file then
    file:write(string.format(
      "notes=%d\nccs=%d\nsysex=%d\nnote36=%d\ncc119=%d\n",
      notes, ccs, sysex, note36, cc119
    ))
    file:close()
  end

  for item_index = reaper.CountTrackMediaItems(track) - 1, initial_items, -1 do
    reaper.DeleteTrackMediaItem(track, reaper.GetTrackMediaItem(track, item_index))
  end
  reaper.UpdateArrange()
end

local function finish()
  reaper.Main_OnCommand(1016, 0) -- Transport: Stop
  stopped_at = reaper.time_precise()
  reaper.defer(inspect_and_cleanup)
end

local function wait_for_capture()
  if reaper.time_precise() - started >= 5 then
    finish()
    return
  end
  reaper.defer(wait_for_capture)
end

reaper.defer(wait_for_capture)
