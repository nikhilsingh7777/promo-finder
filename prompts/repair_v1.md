You fix promo clips for vertical microdramas. A previous candidate broke hard rules.
The code measured it; trust the measured numbers, not your own estimate.

Rules: {{min_dur}}-{{max_dur}} s total (aim {{target_min}}-{{target_max}} s); the hook event starts within {{hook_window}} s of the
clip start and the opening seconds contain a line or action, not just camera shots; the
cliffhanger event is at the end of the last segment (the clip ends within {{cliff_tail}} s after it);
segments use only event IDs from the transcript, in story order, without overlap.

Change as little as possible: move start/end event IDs, or pick a different hook/cliffhanger
event nearby. Keep the same moment of the story.

Return ONLY a JSON object with a single candidate, same schema as before:
{"segments": [{"start_event_id": "..", "end_event_id": ".."}], "hook_event_id": "..",
 "hook_description": "..", "cliffhanger_event_id": "..", "cliffhanger_description": "..",
 "unresolved_question": "..", "why_it_works": "..", "confidence": 0.0}
