# Website stories

Plan for turning the page into a mobile-first flow with four beats:
**Where am I**, **Making it**, **Your dial today**, **Take it home**. Written as
user stories with acceptance criteria so each can be built, checked and shipped
on its own.

```
1 Where am I?  ->  2 Making it  ->  3 Your dial today  ->  4 Take it home
   locate/confirm     facts in 2 s     3D at now, or         ZIP, part previews,
   Generate           progress         first light tomorrow  donate
        \                                                        /
         `----------------- More (one tap away) ----------------'
                 settings, accuracy, setup, the story
```

One screen per beat on a phone. The 3D view is the constant; it enters at
beat 2 and stays pinned through beats 3 and 4. Everything explanatory lives
one tap away and never in the path.

## Ground rules

* **Mobile first.** Every story is accepted on a 390 px phone before desktop.
  Desktop is a two-column arrangement of the same components, never different ones.
* **One decision per screen.** The only required input is a place. Everything
  else has a good default and lives behind "More".
* **The 3D view is the reward.** The flow builds towards it and keeps it on
  screen once it exists.
* **Never gate.** The download is never behind a donation, an email or a wait.
  The donate ask is prominent and honest, and says so.
* **Seven languages, RTL included.** Every new string goes through `web/i18n.js`.
  Layout is checked in Arabic.

Effort: S under a day, M one to three days, L a week. "Must" = first release.

---

## Epic 1 · Where am I?

A visitor opens the page on a phone and, within ten seconds, has a place
confirmed and one big button to press.

### S1.1 Open on the question (Must, S)
As a visitor on a phone, I want the page to open on "where are you?" so that I
know what to do before I read anything.

* Above the fold on 390 × 844: one-line title, one sentence of promise, the
  location card, the primary button. No 3D canvas yet, no chapters.
* The story chapters (why the roller, Bernhardt, the analemma) move below the
  flow, reachable by scrolling or a "Why does this work?" link.
* Exactly one primary button: "Make my sundial" (i18n, all seven languages).

Today: the page opens on a hero with a 3D stage and long chapters before the
generator. Language selector and static demo mode stay.

### S1.2 Use my location (Must, S)
As a visitor, I want to tap "Use my location" and see my place named so that I
don't have to type anything.

* Geolocation is asked only after the tap, never on load.
* Within two seconds of a fix the card shows a place name (Nominatim reverse
  geocode), coordinates to two decimals with N/S/E/W, and the time zone in
  words: "CET, with summer time (CEST)" or "UTC+8, no summer time".
* Denied/failed geolocation falls back to the search field with a calm one-line
  message, no error styling.
* Map hidden by default on phones; "Adjust on map" expands it under the card.
  Visible beside the card on desktop.

Today: geolocation, search and timezone lookup exist in `app.js`; the map is
always rendered (Leaflet tiles on every visit).

### S1.3 Search a place (Must, S)
As a visitor, I want to type a town and pick it from a short list so that I can
make a dial for a place I am not standing in.

* Search field, Enter submits. Up to five results with country; a tap fills the card.
* "48.78, 9.18" or "48.78 N 9.18 E" is parsed without a lookup.
* Last confirmed place remembered on this device (localStorage in try/catch),
  offered next visit as "Stuttgart again?".

Today: search takes the first Nominatim hit silently.

### S1.4 A hint before the button (Must, S)
As a visitor, I want a hint of what I will get before I press the button so
that pressing it feels safe.

* The card shows two derived lines that update instantly with the place: the
  dial's tilt (= latitude) and the engraved hour range. Cheap call, no meshing.
* Outside the good latitude band the card says so before generating (below 27°
  "the winter sun will shade the dial", polar circle "hours 3 to 21"). Same
  words as the existing warnings, moved earlier.
* One quiet line: "150 mm dial · engraved for 2026 · change". "Change" opens More.

Needs: `GET /api/design?lat&lon&utc_offset_h&year` running `build_design` only
(hour range, sunrise/sunset extremes, tilt, roller profiles, noon analemma).
`build_design` is well under a second; only `build_all` is slow.

---

## Epic 2 · Making it

Generation takes on the order of a minute. The visitor should feel the dial
being shaped for their sky, not stare at a spinner, and never wonder whether
the page has hung.

### S2.1 Facts within two seconds (Must, M)
As a visitor who pressed the button, I want real facts about my dial within two
seconds so that the wait has already paid something back.

* The screen changes to the Making view: place name as heading, a fact list
  filling in line by line over two seconds: longest day (sunrise to sunset,
  clock time), engraved hours, minute ticks yes/no, roller waist from x to y mm,
  tilt, whether the dial gets a summer-time row.
* The analemma for this place draws itself (stroke animation ~2.5 s, respects
  reduced motion), month initials appearing as the line passes. Same figure
  that becomes the base plate.
* The two roller profiles fade in beside it with the solstice dates.

Needs: the fast design endpoint called first; the slow generate call starts in
parallel. `drawAnalemma` and `drawProfiles` exist in `viewer-core.js`.

### S2.2 Real progress (Must, L)
As a visitor, I want to see which part is being made right now and how far
along it is so that I trust the page is working.

* Progress line with five named stages in order: "Shaping the dial", "Cutting
  the numerals", "Turning roller I", "Turning roller II", "Casting the base".
  Each ticks when the backend reports it; a time-based estimate moves the bar
  in between so it never stands still for more than a second.
* Estimates from the median of the last ten builds on this server per stage,
  so it is honest on a slow free tier and a fast machine.
* Cached result: Making view is skipped after the facts have shown for one second.
* Closing the tab and returning within ten minutes resumes the same job (job id
  in sessionStorage).
* Failure shows the reason in plain words, keeps the facts on screen, offers
  "Try again" and "Try with a smaller dial".

Needs: generation becomes a job. `POST /api/generate` returns `{job, cached}`
at once; `GET /api/jobs/{job}` streams server-sent events (stage, done,
elapsed) and ends with the info payload. `build_all` gets a progress callback
between `build_dial`, engraving, each roller and `build_stand`. One worker
process with a queue is enough; queue position shown as a stage of its own
("Waiting behind 2 dials").

### S2.3 Something to look at (S)
As a visitor, I want something to read or look at while the parts are built so
that the minute feels short.

* Three short cards rotate every eight seconds: why the roller has a waist, why
  two rollers, why the base is the analemma. Three sentences each, chapter as
  "read more".
* Today's sun path for the place drawn as an arc with the current sun marked
  (same solar maths as the viewer).
* Nothing requires a tap; nothing auto-scrolls. When the meshes arrive the 3D
  view fades in over the top and the rest collapses.

---

## Epic 3 · Your dial today

The first 3D frame the visitor sees is their own dial, in their own sunlight,
at this moment. If the sun is down, it is tomorrow's first light.

### S3.1 Now (Must, M)
As a visitor, I want the dial shown at the current time in my place so that I
can compare the shadow with my phone's clock right now.

* Viewer opens at the place's current zone time (device clock + place's UTC
  offset, summer time applied when the zone has it and the date is inside it).
  Readout: "Now, 14:37 · 26 September".
* Correct roller for the date fitted and named; shadow edge on the minute.
  Readout shows "sun 5.6 min ahead of the clock".
* Camera starts on the pole side, slightly above (reading position); the sun
  sweeps in from sunrise to now over 2.6 s as today.
* Time scrubbable with the slider; "Now" chip snaps back.

Today: viewer opens at 12:00 on 20 May of the design year. Sweep, roller choice
and readout exist. Browser-side summer-time bookkeeping needs the zone name
(already returned as `tz` by `/api/timezone`).

### S3.2 Tomorrow if no sun (Must, S)
As a visitor at night, I want to see the dial at tomorrow's first useful light
so that I still get a real reading, not a dark scene.

* If the sun is below the horizon now, or the hour is outside the engraved
  range, the viewer opens at the first engraved hour after the next sunrise:
  "Tomorrow, 7:00 · first light on the dial".
* Polar night: search continues day by day and the readout names the date.
* Chip row becomes "Now · Tomorrow morning · Noon · 21 June · 21 December".

Today: `sunriseMinutes` exists; below-horizon and outside-hours states are
detected in `setTime`.

### S3.3 One accuracy line (S)
As a visitor, I want a single line under the 3D view telling me how accurate
this dial will be so that I know what I am printing.

* "Reads the clock to the minute all year" or "Within 2 minutes from 3 to 15
  March", from the existing accuracy report.
* Shadowed days as a second sentence. API warnings appear here in the same
  tone, not as a red list.
* "Details" opens the full facts (Epic 5).

### S3.4 Touch (M)
As a visitor on a phone, I want to move around the dial with one finger and not
fight the page scroll.

* Canvas full width, 4:5 on portrait phones, 16:9 on desktop. One finger
  orbits, two fingers zoom, page scrolls only when the drag starts outside.
* Pixel ratio capped at 2; render loop pauses when off screen.
* "Apart" (exploded view) becomes a toggle chip in the canvas corner.

---

## Epic 4 · Take it home

Downloading is one tap. Everything a maker might want to know before printing
is one more tap, and the thank-you ask stands beside the download without ever
standing in front of it.

### S4.1 One button (Must, S)
As a visitor who likes what I see, I want one obvious button that gives me
everything so that I don't have to understand the parts first.

* Directly under the 3D view, full-width primary button "Download the sundial
  (ZIP, 4 parts)" with the size in MB. Appears the moment the meshes load, same
  screen as the viewer.
* ZIP keeps README.txt and gets a real name from place slug and size, e.g.
  `sundial-stuttgart-150mm.zip`.
* Muted line under it: "STL files for any printer · sized for a 220 mm bed",
  bed figure computed from the largest part.

### S4.2 Preview the parts (Must, M)
As a maker, I want to see each part alone, lying as it should on the print
bed, so that I know the orientation before I open a slicer.

* "Preview the parts" expands four tiles: Dial, Roller I, Roller II, Base. Each
  is a small live 3D render of that part alone on a grey build plate with a
  10 mm grid, in print orientation: dial scale side up, rollers pin down, base
  plate down.
* Each tile: size in mm (x × y × z on the bed), volume in cm³, estimated weight
  at PLA density 1.24 g/cm³ ("solid, before infill").
* Support hints from the README: "tree supports under the wings and hub",
  "supports under the bell", "no supports above 25° latitude".
* Each tile has its own "Download dial.stl" link. Tapping a tile enlarges it
  to the full stage with orbit.

Needs: per-part bounds already in `info.bounds`; volume is one trimesh call per
part and joins the info payload. Print orientation is a fixed rotation per
part; bed hint rounds the largest footprint up to 180/220/250/300 mm.

### S4.3 Donate beside download, no dark patterns (Must, S)
As the maker of this site, I want a clear, prominent donate button beside the
download so that people who value the work can say thanks, without anyone
feeling pushed.

* Download and donate side by side on desktop, stacked on phones. Download
  first and primary (brass fill); donate second and clearly secondary
  (outlined, same height and radius, not smaller, not greyed out).
* Donate reads "€1 for the maker" with a PayPal mark and one line: "Optional.
  The files are yours either way." Links to paypal.me/pinguinonice/1EUR in a
  new tab.
* No interstitial, no countdown, no pre-ticked box, no reminder after the
  download, no "are you sure". The download starts on the first tap every time.
* After a download tap the donate line gains a small "Thank you for printing
  one" and nothing else changes.

### S4.4 Notes one tap away (S)
As a maker, I want the print and setup notes one tap from the download so that
I do not need to find the README later.

* "Print notes" and "Setting it up" as two collapsed sections under the
  download row. Print notes: layer height, supports per part, thread needs no
  calibration, screw the roller in until the collar seats. Setting up: the
  four existing steps (level, aim at true north, seat the dial, choose the
  roller) with the pole-side wording.
* Same text as README.txt from one source of truth (i18n strings rendered
  server-side or shared JSON), so the two never drift.
* "Share this dial" copies a link encoding place, size and year; reopening
  lands on Making with those values (cache hit makes it instant).

---

## Epic 5 · More, one tap away

Nothing in Epics 1 to 4 asks the visitor for a number. The people who want
numbers get all of them here.

### S5.1 Settings sheet (Must, S)
As a tinkerer, I want to change dial size, hour range, year and roller waist
so that the dial fits my printer and my taste.

* Bottom sheet on phones, side panel on desktop, opened from "change" on the
  location card or "Adjust" next to the download. Fields: diameter (slider
  80 to 300 mm with the bed hint live), year, hours automatic or first/last,
  minimum roller radius, zone label and summer label as text, manual UTC offset.
* Any change shows "Regenerate" as the primary action and returns to Making;
  the previous result stays downloadable until the new one arrives.
* Defaults restorable with one tap.

### S5.2 Full details (S)
As a curious visitor, I want the full facts of my dial so that I can check it
against what I know.

* "Details" under the 3D view opens the full facts list: place, hours, longest
  day, roller radii, tilt and plate size, dial footprint, accuracy by date
  range, shadowed days, tip-over angle from the stability report, thread pitch
  and clearance.
* The analemma and roller-profile figures live here with their captions.

### S5.3 Keep the story (S)
As a reader, I want the story of the roller sundial to still be on the site so
that the page keeps its character.

* The existing chapters become a "Why this works" section below the flow,
  text unchanged; footer sources stay.
* `web/build_demo.py` renders the Stuttgart result into the same four-beat
  layout starting at beat 3, so the hosted preview and the live site match.

---

## Order of work

Three slices. Each leaves the site working and shippable.

| Slice | Stories | What the visitor gets |
|---|---|---|
| 1 · Flow | S1.1 S1.2 S1.3 S1.4 S4.1 S4.3 S5.1 S5.3 | Mobile-first four-beat layout with today's synchronous generation, the download row and donate beside it. Frontend plus the fast design endpoint. |
| 2 · Making | S2.1 S2.2 S2.3 S3.1 S3.2 S3.3 | Real progress from a job endpoint, facts and analemma during the wait, the viewer opening at now or tomorrow's first light. |
| 3 · Parts | S4.2 S4.4 S3.4 S5.2 | Part previews on a build plate with weights and support hints, print notes from one source, share links, better touch handling. |

## Open questions

* **Server.** The free Render tier sleeps, so the first visitor of the day
  waits for a cold start before the job begins. Show it as a stage ("Waking
  the workshop") or pay for an always-on instance?
* **Weight.** Quote solid weight at PLA density, or a slicer-style estimate at
  15 % infill? Solid is honest and simple; infill is closer to the slicer.
* **Donate amount.** Keep the fixed €1 link, or 1 / 3 / 5 as three plain
  buttons, none preselected?
* **Share links.** Place slug plus size in the URL hash is enough for a cache
  hit. Fine to expose coordinates to two decimals in a share link?

Everything above builds on code already on the branch: the geometry, the
timezone lookup, the viewer, the seven-language strings and the cache keyed by
request. The only new backend pieces are the fast design endpoint and the job
with progress events.
