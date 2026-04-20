# Vinyl-Broadcast Ethics: Hip-Hop Scene Norms, Beat-Scene Practice, and the Moral Economy of Producer Livestreams

Status: research
Date: 2026-04-20
Operator: single hip-hop producer ("LegomenaLive" YouTube channel) — Handytraxx Play vinyl rig through Erica Synths MIDI Dispatch → Endorphin.es Evil Pet (granular) + Torso S-4 → Studio 24c → PipeWire → YouTube Live RTMP
Parent: `docs/research/2026-04-20-vinyl-collection-livestream-broadcast-safety.md` §6 (this document deepens the ethical layer; the parent is the legal/platform layer)
Register: engaged-practitioner. Prefers practitioner voices, scene press, and label-policy primary sources over general-audience copyright explainers.

---

## §1 TL;DR — the moral contract and three commitments operator can make this week

The hip-hop sampling tradition is governed less by black-letter copyright than by an unwritten **moral contract** between practitioner and source: take what you need to transform, but transform it; credit the source publicly via interviews, liner notes, on-stream callouts, and oral tradition; never lurk in silence; make the listener want to find the source. Producers in the J Dilla / Madlib / Knxwledge / Pete Rock lineage all uphold this contract — even when they are sampling without clearance, even when they are taking from records the law would call infringement. The contract is satisfied by *honor* (treating the source as an artist whose work matters) and *transformation* (making the new thing recognizably new). It is violated by *silence* (uncredited rip-and-stream, blog-bot extraction, AI scraping) and by *erasure* (processing that strips intent without acknowledging the original).

A vinyl-broadcast livestream is a near-perfect arena to practice the moral contract well — or to violate it badly. The legal exposure is real (parent doc §2–§6) but the *ethical* exposure is the more consequential one for a producer who identifies as part of the beat scene: the scene reads behavior, and the people who get cited respectfully (Knxwledge, MNDSGN, Karriem Riggins, Madlib) are the ones who name the records they love.

**Three concrete ethical commitments operator can announce on the channel this week:**

1. **Live attribution floor.** Every spin gets an on-screen now-playing chyron with **artist + label + Bandcamp/Discogs link**, present for the *entire* duration of the spin (not just intro/outro), in a region of the frame that survives heavy granular processing. Tooling exists: Serato Now Playing, *What's Now Playing* (open-source), Pioneer Prolink Tools — but operator is on a Handytraxx Play (no metadata feed), so this is operator-curated text from a per-set queue file, not auto-detected. The commitment is the *practice*, not any specific tool. ([Now Playing App](https://www.nowplayingapp.com/); [Serato Now Playing Twitch extension](https://support.serato.com/hc/en-us/articles/360001991976-Using-the-Serato-Now-Playing-Twitch-extension); [whats-now-playing on GitHub](https://github.com/whatsnowplaying/whats-now-playing))

2. **Direct economic flow.** Stream tips are routed monthly to the artists spun, weighted by spin time, via Bandcamp purchases logged in a public ledger (a pinned community post or a static page on the channel's About). Bandcamp's revenue share is the lowest of the practitioner-supportive platforms (~82% to artist), and Bandcamp Friday (the first Friday of every month, plus expanded 2026 schedule) waives Bandcamp's revenue share entirely. ([Bandcamp Fridays 2025 announcement](https://blog.bandcamp.com/2025/03/04/why-bandcamp-fridays-matter-even-if-youre-not-releasing-new-music/); [Bandcamp Friday Help](https://get.bandcamp.help/hc/en-us/articles/23006342800407-Bandcamp-Friday-Help))

3. **Public no-play list and good-faith protocol.** A short public statement on the channel's About: "Operator does not broadcast: (a) artists who have requested not to be broadcast, (b) labels that have asked us not to play their catalog, (c) artists whose tracks have been DMCA'd against this channel and who have not subsequently invited the channel to resume." A linked, openly-editable list (e.g. a GitHub gist) of removed artists/labels, and a stated good-faith response posture: takedown → immediate removal → outreach within 7 days asking whether the artist wants to be permanently excluded or wants to discuss terms.

These three commitments are publishable as a single short channel-About paragraph + a linked "Vinyl Broadcast Ethics" page. They cost the operator nothing in stream quality, signal scene-aware practice to other producers, and create real economic flow back to artists.

---

## §2 Hip-hop's sampling-ethics tradition — the unwritten contract

### §2.1 Sampling as folk-art, sampling as quotation

Public Enemy's Chuck D famously likened sampling to **folk art** — passing down musical riffs the way oral tradition passes down stories. Scholars of African American music describe sampling as a form of **musical quotation**, structurally analogous to vernacular **signifyin(g)**, where citing prior material is itself a creative and respectful act, not an extractive one. ([CUNY: Sampling in Hip-Hop / aesthetics of community and tradition](https://academicworks.cuny.edu/cgi/viewcontent.cgi?article=1029&context=le_etds); [UBC: Sampling in Hip-Hop / aesthetics analysis](https://open.library.ubc.ca/media/stream/pdf/24/1.0450749/4))

In this tradition, the morally relevant axis is not "did you get permission" — it is "did you take seriously the work you're quoting." Pete Rock spells this out: he prefers obscure samples *over* big-name samples specifically because it lets him "keep the vibe of the original records just to show some respect musically." Respect is *demonstrated* by the way you handle the sample, not by the existence of a clearance form. ([HotNewHipHop: Pete Rock on sampling and crate-digging](https://www.hotnewhiphop.com/321011-pete-rock-explains-his-sampling-process-the-power-of-jazz-and-why-crate-digging-will-never-die-news); [HipHopDX: Pete Rock on the art of sampling](https://hiphopdx.com/news/id.15755/title.pete-rock-talks-the-art-of-sampling-names-his-three-favorite-productions); [Hip Hop Golden Age: Crate Diggers — Pete Rock](https://hiphopgoldenage.com/crate-diggers-pete-rock/))

### §2.2 Bridgeport's chilling effect and the crate-digger's response

The Sixth Circuit's *Bridgeport Music v. Dimension Films* ruling (parent doc §2.6) imposed a bright-line "get a license or do not sample" rule for sound recordings. NYU musicologist and sampling expert Lawrence Ferrara called the case "extremely chilling, because it basically says that whatever you sample has to be licensed, in its most extreme interpretation." ([Wikipedia: Bridgeport Music v. Dimension Films](https://en.wikipedia.org/wiki/Bridgeport_Music,_Inc._v._Dimension_Films); [DePaul Law Review: How the Sixth Circuit missed a beat](https://via.library.depaul.edu/cgi/viewcontent.cgi?httpsredir=1&article=1343&context=law-review); [Indiana Law Journal: Mueller on Bridgeport and de minimis](https://ilj.law.indiana.edu/articles/81/81_1_Mueller.pdf))

The producer-community response to Bridgeport was *not* to stop sampling — it was to **dig deeper**: into rarer records, into smaller pressings, into countries with weaker enforcement, into the specifically-uncleared corners of the crate. The crate-digger's ethic *intensified* in the Bridgeport era. Dilla's *Donuts* (2006) and Madlib's *Madvillainy* (2004) are both products of this intensification. The takeaway: the legal regime forced the practice underground, but the moral contract — transformation + acknowledgment — survived and arguably hardened. ([escholarship: From Mozart to Hip-Hop / Bridgeport's impact](https://escholarship.org/content/qt61k2v6tz/qt61k2v6tz_noSplash_6d0d0e48df9240ff1581efded0d807c8.pdf))

### §2.3 J Dilla — the sample as collaborator

J Dilla's approach in *Donuts* was unusually horizontal: he chopped fewer drum-only or instrumental-isolated breaks and instead let full-band passages **breathe** through the beat. At points he let the original tunes play a few bars before flipping them. This is a producer choosing to *show his sources* even within the work itself — a kind of **structural attribution**. ([Perfect Circuit: J Dilla's Donuts retrospective](https://www.perfectcircuit.com/signal/j-dilla-donuts); [Stephen F. Austin scholarship: Analysis of Sampling Techniques by J Dilla in Donuts](https://scholarworks.sfasu.edu/cgi/viewcontent.cgi?article=1211&context=etds); [The Babble: J Dilla & The Art of Sampling](https://thebabblejournal.com/issueone/jdillaartofsampling); [Columbia Journal of Law & the Arts: Happy Birthday J Dilla — A Case for Sampling Under Copyright Law](https://journals.library.columbia.edu/index.php/lawandarts/announcement/view/681))

Notably, *Donuts* itself attracted post-mortem litigation: 10cc sued Dilla's estate over "The Worst Band in the World" sample. The estate's posture (and the scene's response) implicitly accepted the legal exposure as a *cost of practice*, not as a moral defeat. The work was already in the canon; the lawsuit did not retroactively make it dishonorable.

### §2.4 Madlib — the digger as scholar

Madlib's posture in interviews is consistently anti-shortcut. From *The Wire*: "I never use a computer. It's too easy. It's not easy to sound like Dilla, but you can make beats like Dilla with your computer, so that's why everybody sounds like Dilla." From *Stones Throw* / collected interviews: he doesn't just buy records to sample — he wants to **understand** each song; he doesn't need to know the language to perceive musicality. ([EARMILK: The Wire interviews Madlib](https://earmilk.com/2009/07/15/the-wire-interviews-madlib/); [Stones Throw: Sound Pieces — Madlib Interview](https://www.stonesthrow.com/news/sound-pieces-madlib-interview/); [The Quietus: The Strange World of Madlib](https://thequietus.com/articles/26665-madlib-madvillain-quasimoto-review); [Bandcamp Daily: Crate-Digging Depths of Madlib's Medicine Show](https://daily.bandcamp.com/lists/madlib-medicine-show-list); [Passion of the Weiss: The Madlib Mystique](https://www.passionweiss.com/2023/08/24/madlib-interview-la-weekly-2010/))

The implicit ethic: the producer earns the right to chop a record by *learning* it first. The vinyl-broadcast operator is in an even more direct version of this relationship — they're not just sampling, they're *playing the whole thing back*. The earned-right is correspondingly stronger and the attribution obligation correspondingly heavier.

### §2.5 Knxwledge — the volume and the obscurity

Knxwledge's interviews (FACT, FADER, Bandcamp Daily, Hypebeast, Ableton, DJBooth, The Hundreds, Acclaim) consistently portray a producer who **dumps drafts publicly** (Bandcamp's `bapethoughts` series, hundreds of beats on Soundcloud) rather than gating them. He came to Stones Throw via Boiler Room — Peanut Butter Wolf saw him spin a Charizma remix and signed him on the strength of the live demonstration. ([Bandcamp Daily: Knxwledge breaks down 1988](https://daily.bandcamp.com/features/knxwledge-1988-interview); [The Hundreds: A Conversation with Knxwledge](https://thehundreds.com/blogs/content/knxwledge-interview); [FACT: An interview with Stones Throw's Knxwledge](https://www.factmag.com/2015/05/31/knxwledge-interview/); [The FADER: Beat Construction — Knxwledge](https://www.thefader.com/2015/05/19/beat-construction-knxwledge); [Hypebeast: Knxwledge talks 1988](https://hypebeast.com/2020/4/knxwledge-1988-album-interview); [Ableton: Knxwledge — Staying in Go Mode](https://www.ableton.com/en/blog/knxwledge-staying-in-go-mode/); [DJBooth: Knxwledge has no idea he's one of hip-hop's rising producers](https://djbooth.net/features/2015-04-22-knxwledge-producer-interview/); [XLR8R: Rapper Proof — Knxwledge](https://xlr8r.com/features/rapper-proof-how-hardworking-la-beatmaker-knxwledge-became-the-most-known-unknown-producer-in-the-game/); [Acclaim: Knxwledge talks Hud Dreems](https://acclaimmag.com/music/interview-knxwledge/))

For a livestream operator, Knxwledge models a posture: **show the work, including the loose ends**. Stream the digging, the bad takes, the half-thought-through transitions. The honesty is itself a form of attribution — it makes clear that what you're doing is *practice*, not *product*, and that practice is in continuous dialogue with the records you're playing.

### §2.6 RZA — the evolved sampling ethic

RZA's interviews trace an explicit *evolution* in his sampling ethics. Early Wu-Tang work was deep crate-digging (Screamin' Jay Hawkins, Wildman Steve, Philadelphia Orchestra "Peter Pan"). Later, he was confronted by a session musician who told him "You're ruining music" — sampling had displaced studio work for working musicians. RZA responded by *learning music theory* and producing more from scratch, while still defending sampling: he argues the sampler is an instrument and that an original copyright holder of a sampled work should not get 100% — he believes 50% is the maximum. ([Tape Op: RZA on Wu-Tang's production](https://tapeop.com/interviews/163/rza); [NPR Fresh Air: 50 years of hip-hop, RZA](https://www.npr.org/2023/09/01/1197210646/fresh-air-celebrates-50-years-of-hip-hop-wu-tang-clans-rza); [Ambrosia for Heads: RZA's controversial views on sample lawsuits](https://ambrosiaforheads.com/2015/03/rza-has-some-controversial-views-on-sample-lawsuits-in-2015-do-you-agree/); [MTV: RZA recalls being challenged to stop sampling](https://www.mtv.com/news/nsf8a6/rza-wu-tang-sampling); [Acclaim: Origins, intricacies — RZA interview](https://acclaimmag.com/music/interview-rza/); [unkut: The RZA Interview](https://unkut.com/2014/12/the-rza-the-unkut-interview/))

The lesson for vinyl-broadcast: an *evolving* ethic is itself a sign of seriousness. Broadcasting practice should be expected to change — the operator's responsibility is to be in *visible dialogue* with that change, not to defend a static position.

### §2.7 The liner-notes tradition

Brian Coleman's *Check the Technique* series (Vols. 1 & 2) — with foreword by Questlove — collected oral histories from RZA, Big Daddy Kane, Muggs, B-Real, Biz Markie, Ice-T, Wyclef and dozens more, walking through the influences, equipment, samples, beats, and creative decisions on classic records. The series exists because **liner notes used to be skippable shout-outs**; the scene needed a separate venue for the actual production-ethics discussion. ([Amazon: Check the Technique](https://www.amazon.com/Check-Technique-Liner-Hip-Hop-Junkies/dp/0812977750); [Word Is Bond: Check the Technique Vol. 2 review](https://www.thewordisbond.com/check-technique-volume-2-liner-notes-hiphop-junkies-book-review/))

The vinyl-broadcast equivalent is **the on-stream commentary**. An operator who occasionally drops the production context of a record being played ("this is the original Knxwledge sampled on `meek.vol.31`," "Pete Rock used this exact Brand New Heavies record on…") is fulfilling the liner-notes function in real time. This is not just attribution — it is the *propagation of the tradition*.

---

## §3 Scene practice: who is streaming and how they handle attribution

### §3.1 Boiler Room — the cleared, branded model

Boiler Room is the highest-profile beat-and-club livestream brand. Its 2020 Apple Music partnership was structured to **compensate every artist whose track appears in a set**, alongside the DJ. Boiler Room negotiated this directly because DJ-mix royalty plumbing across major streaming services was historically broken. ([Music Ally: Boiler Room brings mixes to Apple Music — and DJs get paid](https://musically.com/2020/08/20/boiler-room-brings-mixes-to-apple-music-and-djs-get-paid/); [The FADER: Boiler Room partners with Apple Music](https://www.thefader.com/2020/08/19/boiler-room-partners-with-apple-music-to-bring-its-mixes-to-the-platform); [5 Magazine: Boiler Room Is Changing](https://5mag.net/features/boiler-room-is-changing/); [Wikipedia: Boiler Room](https://en.wikipedia.org/wiki/Boiler_Room_(music_broadcaster)); [Reprtoir: The Boiler Room Model and the Current State of the DJ Livestream Sector](https://www.reprtoir.com/blog/electronic-music-boiler-room))

Attribution practice: Boiler Room sets historically did **not** carry on-screen track IDs — the camera focuses on the DJ and the crowd, and the ethic was "if you want to know what's playing, you ask the DJ later or you Shazam." This is part of the **mystique tradition** — the set is a performance, not a database. Operator should note: this is the *opposite* model from what's recommended in §1. Boiler Room can sustain the no-attribution ethic because (a) the brand has license deals so the artists are still paid, and (b) the cultural cachet of the unidentified spin is part of the brand. A solo producer with neither license deals nor that cultural cachet is structurally in a different position.

The lesson: there is a defensible ethic of *aesthetic attribution-restraint* (the Boiler Room ethic) **only when economic attribution is being handled separately**. Without the economic flow, attribution-restraint becomes attribution-suppression, which is the violating posture.

### §3.2 NTS Radio — license-pays-everywhere, total curatorial freedom

NTS pays royalties to a comprehensive list of collection societies (BMI, ASCAP, SESAC, SoundExchange, PRS, PPL, GEMA, SGAE, KODA, SABAM, BUMA/STEMRA, APRA/AMCOS, JASRAC, SACEM, SPRE, ENTANDEM, IMRO, ECAD), and explicitly prioritizes **human curation over algorithmic recommendation**. Founder Femi Adeyemi: the station was a response to a "homogenous radio climate" — the goal was to make space for "every taste in London" and let hosts curate without policy interference. ([NTS About](https://www.nts.live/about); [NTS: Licensing and Royalty Fees](https://ntslive.freshdesk.com/support/solutions/articles/77000586376-licensing-and-royalty-fees); [Music Business Worldwide: We are not just a digital utensil for listening to music](https://www.musicbusinessworldwide.com/we-are-not-just-a-digital-utensil-for-listening-to-music/); [Mixmag: An oral history of NTS Radio](https://mixmag.net/feature/nts-radio-oral-history); [Wikipedia: NTS Radio](https://en.wikipedia.org/wiki/NTS_Radio))

Attribution practice: NTS sets carry **per-track now-playing chyrons** (track + artist + label) on the live web player. The chyron is distinct from the visual focus of the stream and is updated by the host's pre-loaded set list. This is the model the operator should study most closely — it's the same posture the operator needs (single curator, deep-record collection, small audience) at a higher scale.

### §3.3 Dublab — the 25-year gold standard

Dublab (founded 1999, Los Angeles, non-profit) operates outside FCC strict-format regulation precisely to give curators creative freedom. Its 2-hour shows have **no required guidelines, no promo plugs, no format constraints**. Through community-generated radio, Dublab promotes "curiosity, experimentation, inclusivity, and connection." Its 25-year run is in itself the credential. ([Wikipedia: Dublab](https://en.wikipedia.org/wiki/Dublab); [Dublab About](https://www.dublab.com/aboutdetail); [The FADER: At 25, Dublab is still the gold standard](https://www.thefader.com/2024/12/12/dublab-online-radio-station-25-anniversary-interview); [MusicTech: Dublab still the champion of independent online radio](https://musictech.com/features/interviews/dublab-online-radio-25-years/); [Beatportal: Future Roots Forever — Dublab](https://www.beatportal.com/articles/313517-future-roots-forever-how-las-dublab-revolutionized-online-community-radio))

Attribution practice: Dublab maintains rotating per-show track listings (post-broadcast and during live sessions on the player UI). The *Bandcamp* of Dublab sessions is itself a model — every show is archive-able with the artist credits attached.

### §3.4 Gilles Peterson / Worldwide FM — radio veteran posture

Gilles Peterson founded Worldwide FM in 2016 as an extension of his BBC Radio shows. Worldwide FM highlights "underground music, culture and stories from around the globe," operates as a freeform internet radio service. Track-ID culture is integral to Peterson's broadcast practice — he was a radio host long before livestreaming, and the BBC tradition is **"every track gets named, on air, before or after."** ([Wikipedia: Gilles Peterson](https://en.wikipedia.org/wiki/Gilles_Peterson); [Wikipedia: Worldwide FM](https://en.wikipedia.org/wiki/Worldwide_FM); [Worldwide FM About](https://www.worldwidefm.net/); [Gilles Peterson Worldwide on Mixcloud](https://www.mixcloud.com/gillespeterson/))

### §3.5 Kenny Beats Twitch — the production-mentorship model

Kenny Beats' Twitch channel (active since March 2020) is a different beast: it's a **producer Twitch stream**, not a DJ stream. Beat battles, sample-flips on viewer-submitted material, beat-doctor sessions with named producers (oksami, SPELL, Matt Zara). The samples used are typically odd / public domain / cleared (Jeopardy clips, MJ shopping spree audio). Attribution is via in-stream callouts to the contestants. ([Twitch: Kenny Beats channel](https://www.twitch.tv/kennybeats); [La Tonique: Kenny Beats, Twitch and the Evolving Music Industry](https://www.latonique.news/articles/kenny-beats-twitch-and-the-evolving-music-industry); [Bloomberg: Twitch's streaming boom is jolting the music industry](https://www.bloomberg.com/news/articles/2020-06-18/twitch-s-streaming-boom-is-jolting-the-music-industry); [Lucid Monday: Matt Zara wins $10k from Kenny Beats' Battle](https://lucidmonday.com/blog/matt-zara-wins-10k-from-kenny-beats-battle-and-a-mix-from-tde-engineer-mixedbyali))

Lesson: the **production stream** posture (Kenny Beats) is structurally cleaner than the **DJ stream** posture (random vinyl) because the source material is selected for cleared/odd-source-ability. A vinyl-broadcast operator can adopt some of the production-stream posture by occasionally **publicly chopping** a record live in the broadcast — which simultaneously demonstrates the source, the technique, and the transformation.

### §3.6 The MF DOOM tribute incident — what *not* to do

A notable cautionary case: in early 2021, Brainfeeder hosted an MF DOOM tribute Twitch stream with Flying Lotus. **The Brainfeeder Twitch account itself was taken down within minutes** of the stream going live, due to DMCA hits — even though the stream was hosted by a label that owned much of the catalog being played. ([Dexerto: Fans furious as MF DOOM memorial stream shut down](https://www.dexerto.com/entertainment/fans-furious-as-mf-doom-memorial-stream-is-shut-down-over-rumored-dmca-issues-1488103/); [Game Rant: Twitch takes down MF Doom Tribute stream hosted by Brainfeeder, Flying Lotus](https://gamerant.com/twitch-mf-doom-tribute-stream-dmca-takedown/))

The takeaway is structural: even **rights-aware label-hosted memorial broadcasts** get killed by automated systems. The ethical posture cannot rely on platforms acting in good faith with the broadcaster — the broadcaster has to build resilience and goodwill independently.

### §3.7 Five streamers/sets the operator should study

1. **NTS Radio live-player chyron behavior** — open NTS Live in a browser during any beat-scene host's set (e.g. *Mafalda*, *Channel One sound system*, *Floating Points* guest sets). Watch how the per-track metadata updates and how it co-exists with the stream's visual aesthetic. This is the cleanest attribution model in the scene.
2. **Dublab archived sessions** (https://www.dublab.com/) — pull a sample of producer-curated 2-hour shows. Note how the archive page lists every track played, with timestamps.
3. **Gilles Peterson Worldwide on Mixcloud** (https://www.mixcloud.com/gillespeterson/) — Mixcloud's licensed model means every spin is identified and the rights holder is paid. Listen to *how* Peterson ID's records on-air mid-set; the rhythm of attribution is itself a craft skill.
4. **Knxwledge's Boiler Room set in LA** (the one that got him signed to Stones Throw) — the *posture* of a producer DJ, the relationship to the records, the way the set is treated as an extension of the production practice. Source via search "Knxwledge Boiler Room LA."
5. **Kenny Beats' Twitch beat-battle archives** — for the contrast: a livestream where the source material is chosen specifically to keep the platform happy (cleared / public-domain / odd source) and the educational/community value is the primary draw. Useful as a contrast model: what livestream looks like when you remove the unmodified-vinyl problem from the equation.

---

## §4 Splattribution in scene context

### §4.1 The term "splattribution" and its scene equivalents

"Splattribution" appears to be Hapax-internal vocabulary — the broader scene does not use this term. The closest scene-equivalents are:

- **"Track ID"** — the colloquial term, used in DJ forums and chat ("Track ID?" is the standard listener question, "ID" as the answer)
- **"Now playing"** — the technical-tooling term (see Serato Now Playing, *What's Now Playing*, Pioneer Prolink Tools)
- **"Set list"** — the post-broadcast equivalent (Boiler Room's "Tracklist" pages, Mixcloud's auto-generated track ID under each upload)
- **"Chyron"** — broadcast-industry term, used by NTS, Dublab, BBC online radio
- **"Notes"** — Dilla-tradition: written commentary that travels with the record

The combination of *real-time on-screen attribution* + *post-broadcast public credit ledger* + *Bandcamp deep-link* is what the operator's "splattribution" describes, and it is approximately what NTS + Mixcloud + Bandcamp together provide. ([Now Playing App](https://www.nowplayingapp.com/); [Serato Now Playing](https://support.serato.com/hc/en-us/articles/360001991976-Using-the-Serato-Now-Playing-Twitch-extension); [whats-now-playing on GitHub](https://github.com/whatsnowplaying/whats-now-playing); [erikrichardlarson/unbox](https://github.com/erikrichardlarson/unbox); [Bombe/obs-dj-overlay](https://github.com/Bombe/obs-dj-overlay); [DJ TechTools: Prolink Tools pulls CDJ data](https://djtechtools.com/2021/01/25/prolink-tools-pulls-cdj-data-to-enhance-dj-sets-share-track-info-into-live-streams/); [DJ Cavon: Serato adds Twitch extension for Track ID](https://djcavon.com/serato-adds-twitch-extension-for-track-id/))

### §4.2 The aesthetic critique of real-time attribution

Some scene practitioners argue that real-time attribution **breaks the mystique** of a set — turns the listener from a participant in a sonic experience into a database scanner ("oh that's that record"). This is a real and respected position; Boiler Room's house style is closer to it.

The operator should note two responses:

- The **mystique critique** is structurally tied to the Boiler Room / club-DJ tradition where the venue or platform is paying for the music. It does not generalize to the solo-producer-on-YouTube case where the broadcaster has no licensing flow at all. Without the economic attribution, aesthetic non-attribution is just lurking.

- A **placement-and-restraint compromise**: keep the chyron in a non-focal region of the frame (lower-third or sidebar), use a quiet typography, let it fade slightly between updates. The Hapax studio compositor (parent council CLAUDE.md § Studio Compositor) already supports this pattern via the Cairo overlay system — operator can render a per-spin attribution chyron alongside album art and the existing token pole / Sierpinski overlays without disrupting the visual aesthetic. The operator's *constitutional* HARDM anti-anthropomorphization principle (memory `project_hardm_anti_anthropomorphization`) generalizes here: the artist is not a face to ventriloquize, but the *credit* is structural information that belongs on the surface.

### §4.3 The "Shazam this in real-time" listener experience

A specific listener pattern to consider: the listener is hearing something they like, want to find the source, and *cannot* — neither because Shazam is going to fail (it does, often, on transformed vinyl) nor because the on-screen chyron is missing. Operator should treat the *listener-can-find-the-source* condition as a target metric. If the operator cannot say "yes, anyone who heard a track they liked could find it within 60 seconds" the attribution layer is not doing its job.

---

## §5 Direct economic-support pathways

### §5.1 Bandcamp — the floor of artist-direct support

Bandcamp's revenue share: 10% on merch, 15% on digital. Average **~82% goes to the artist** (the rest covers Bandcamp's share + payment processor). Bandcamp Friday: Bandcamp **waives its share entirely** on the first Friday of each month (and in 2026, expanded to 8 Bandcamp Fridays). Cumulative Bandcamp Friday flow has exceeded **$120M direct to artists**; the December 6, 2024 Friday alone saw $3.1M in single-day sales. ([Bandcamp For Artists](https://bandcamp.com/artists); [Bandcamp Fridays 2025 announcement](https://blog.bandcamp.com/2025/03/04/why-bandcamp-fridays-matter-even-if-youre-not-releasing-new-music/); [Bandcamp Friday Help](https://get.bandcamp.help/hc/en-us/articles/23006342800407-Bandcamp-Friday-Help); [Wikipedia: Bandcamp](https://en.wikipedia.org/wiki/Bandcamp); [Okayplayer: Independent Artists to Support on Bandcamp Friday](https://www.okayplayer.com/originals/20-independent-artists-to-support-on-bandcamp-friday-october-edition.html); [Bandcamp Daily: Today is Bandcamp Friday](https://daily.bandcamp.com/features/bandcamp-fridays))

For the operator's livestream tip pipeline, Bandcamp purchase is **the highest-fidelity** routing — it delivers near-100% of the dollar to the artist, with public ledger (the Bandcamp account history) as auditable evidence.

### §5.2 Mixcloud — the licensed alternative to YouTube for DJ sets

Mixcloud has unique licensing deals with rights holders, labels, and publishers; their bespoke fingerprinting identifies tracks uploaded; they handle royalties so the creator does not have to worry about copyright takedowns. **65–70% of Creator Subscription revenue goes to artists/labels/publishers**, transaction fees small, **60% of remaining (after costs) goes to the creator**. This is a structurally **artist-aligned** model. ([Mixcloud: How does the Creator Subscriptions revenue model work?](https://help.mixcloud.com/hc/en-us/articles/360004031220-How-does-the-Creator-Subscriptions-revenue-model-work); [Mixcloud: How we pay creators and why we do it](https://www.mixcloud.com/mixcloud/posts/how-we-pay-creators-and-why-we-do-it/); [Mixcloud: Is Mixcloud licensed to play copyrighted music?](https://help.mixcloud.com/hc/en-us/articles/360004185159-Is-Mixcloud-licensed-to-play-copyrighted-music); [DJ TechTools: Mixcloud founder on what DJs need to know about music copyright](https://djtechtools.com/amp/2020/11/18/mixcloud-founder-heres-what-djs-need-to-know-about-music-copyright/); [FACT: Mixcloud Select royalty model breakdown](https://www.factmag.com/2019/06/14/mixcloud-select-royalties/))

The parent doc §1 already recommends Mixcloud Live as the legally-cleared mirror for "selector"-mode programming. The ethical add-on: Mixcloud is **also** the more ethically defensible mirror for non-transformed playback, because the artists actually get paid.

### §5.3 Twitch DJ Program — emerging model

Twitch's DJ Program (2024) offers structurally similar coverage: agreements with UMG, Sony, Warner, etc., DJ pays a percentage of monetization to the rights holders. **VODs / clips / highlights are explicitly NOT covered** — only live. Twitch covers the cost for non-monetizing DJs initially; monetizing DJs split the cost 50/50. ([Twitch: DMCA & Copyright FAQs](https://help.twitch.tv/s/article/dmca-and-copyright-faqs?language=en_US); [Twitch: DJ Program FAQ](https://help.twitch.tv/s/article/dj-program-faq?language=en_US); [Twitch: Music Reporting Process](https://legal.twitch.com/en/legal/dmca-guidelines/music-reporting-process/); [Twitch: Music Guidelines](https://legal.twitch.com/en/legal/music/); [Twitch Blog: Music-Related Copyright Claims and Twitch (2020)](https://blog.twitch.tv/en/2020/11/11/music-related-copyright-claims-and-twitch/); [Twitch: DJ Program Terms](https://legal.twitch.com/en/legal/dj-program-terms/); [Mixmag: Twitch launches update to allow DJs to pay for copyrighted music use](https://mixmag.net/read/twitch-djs-pay-revenue-to-record-labels-news); [Exron Music: Twitch DJ Program reveals streaming without DMCA strikes](https://exronmusic.com/2024/07/27/twitch-dj-program-reveals-streaming-without-dmca-strikes/); [Twitch Music Cleared Carrd](https://twitchmusic.carrd.co/))

This is the operator's **clearest structural alternative** to the YouTube vinyl problem. Operator could dual-stream: YouTube for the transformation-heavy turntablist mode (parent doc §1), Twitch for the more selector-mode unmodified vinyl stretches.

### §5.4 The tip-jar split — proportional Bandcamp routing

Implementation sketch (operator can build this in Hapax in a sprint):

- Per-spin metadata logged to a structured file (artist, label, release URL, spin duration).
- Stream tip pipeline (Streamlabs / Throne / Buy Me a Coffee / Lightning) deposits to a single operator account.
- Monthly cron: aggregate spin time per artist, divide tip pool proportionally, generate Bandcamp purchase queue, execute purchases (Bandcamp doesn't have a programmable purchase API, so this is operator-manual but can be batched the first Friday of the month for Bandcamp Friday).
- Public ledger: pinned post on channel + a simple HTML page on the channel's hapax-officium briefing surface listing the month's allocations.

This is **not normalized in the scene yet** — most beat-scene streamers either don't take tips, take tips for themselves only, or split tips with featured guests. A **publicly-aggregated, artist-routed** tip flow would be a genuinely novel ethical signal.

### §5.5 Patreon norms

Patreon takes 5% commission + 2–4% processing — cheaper than Bandcamp on the platform side. Patreon is structurally a *creator* support tool, not an artist-flow tool. Producers in the beat scene who run Patreons (e.g., many of the *Beat Construction* / *Beat Cinema* / podcast-adjacent producers) typically use it for studio-tour content, sample packs, beat archives. Patreon does NOT solve the artist-attribution problem, but it can fund the *infrastructure* (mics, vinyl purchases, hardware) that lets operator do the broader practice. ([Ari's Take: Turn Your Fans Into Paying Subscribers](https://aristake.com/turn-your-fans-into-paying-subscribers-with-this-platform/); [DJ Mag: How producers can get paid through streaming services](https://djmag.com/longreads/how-producers-can-get-paid-through-streaming-services))

---

## §6 The no-play list — practitioners and labels who say "don't broadcast my work"

### §6.1 Prince's estate

Prince was famously aggressive about copyright control during his life — pulling his catalog from streaming, suing fans for posting unlicensed concert recordings, the well-publicized changes of name and licensing posture. The Prince estate has continued this posture; *Once Upon a Time in Shaolin*-style rights structures (single-copy art objects with broadcast restrictions) explicitly contemplate non-broadcast. ([Creative Commons: Recap of copyright issues surrounding Prince's estate](https://creativecommons.org/2016/05/23/controversy-recap-issues-surrounding-copyright-princes-estate/); [WHGC Law: Prince and the Copyright Revolution Part 1](https://www.whgclaw.com/publications-archive/prince-and-the-copyright-revolution-part-1/); [Consequence: Prince estate sells nearly half of rights](https://consequence.net/2021/07/prince-estate-sells-master-recordings-publishing-name-likeness/))

### §6.2 Wu-Tang and *Once Upon a Time in Shaolin*

The single-copy *Shaolin* album was structurally a broadcast-prohibition art object. RZA has filed multiple lawsuits against Wu-Tang bootleggers. The Morgan Lewis 2025 ruling on Shaolin extended trade-secret protection to musical works, opening new legal territory for artists who want to *prevent broadcast entirely* (not just capture royalties). ([Morgan Lewis: Protecting Art Through Trade Secrets — Wu-Tang ruling](https://www.morganlewis.com/pubs/2025/10/protecting-art-through-trade-secrets-wu-tang-clan-ruling-opens-the-possibility); [Griffith Hack: When copyright collides with a vision — Wu-Tang's Shaolin](https://www.griffithhack.com/insights/publications/when-copyright-collides-with-a-vision-the-tale-of-wu-tang-clans-once-upon-a-time-in-shaolin/); [Complex: RZA files $2M lawsuit against Wu-Tang bootleggers](https://www.complex.com/music/a/cmplxtara-mahadevan/rza-files-2-million-lawsuit-wu-tang-bootleggers-trademark-infringement); [DJ Mag: RZA sells rights to 50% of his songwriting and production credits](https://djmag.com/news/wu-tang-clan-s-rza-sells-rights-50-his-songwriting-and-production-credits))

### §6.3 Lofi Girl and the lo-fi hip-hop community's evolution

The Lofi Girl 24/7 stream's 2022 takedown was via **abusive false copyright claims** — not a true rights-holder objection. The lofi community since has trended toward Creative Commons-licensed and label-owned material to make the broadcast posture unimpeachable. Lofi Girl's own catalog is Lofi Records-released. ([TechCrunch: Youtube ends Lofi Girl's two-year-long stream over bogus DMCA warning](https://techcrunch.com/2022/07/11/lofi-girl-takedown-youtube-music-stream-dmca/); [NPR: Lofi Girl disappeared from YouTube and reignited debate](https://www.npr.org/2022/07/16/1111588405/lofi-girl-youtube-stream-copyright); [The FADER: After the Lofi Girl takedown, can YouTube protect users from copyright claim abuse?](https://www.thefader.com/2022/07/15/after-the-lofi-girl-takedown-can-youtube-protect-users-from-copyright-claim-abuse); [NBC News: YouTube reinstating Lofi Girl streams](https://www.nbcnews.com/pop-culture/pop-culture-news/youtube-says-will-reinstate-lofi-girls-live-streams-false-copyright-cl-rcna37613); [Music Ally: Copyright claim takes down Lofi Girl's YouTube music streams](https://musically.com/2022/07/12/copyright-claim-takes-down-lofi-girls-youtube-music-streams/); [Soundstripe: Lofi Girl Saga and protection against false claims](https://www.soundstripe.com/blogs/lofi-girl-what-creators-can-do-to-protect-against-copyright-claims))

### §6.4 Indie label posture

- **Stones Throw**: Splits 50/50 with artists, transparent accounting, allows artists "free reign over their work" (Peanut Butter Wolf). Stones Throw artists have varied broadcast preferences — operator should research per-artist before adding. ([Stones Throw: Interview with Peanut Butter Wolf](https://www.stonesthrow.com/news/interview-pbw-archive/); [Wikipedia: Stones Throw Records](https://en.wikipedia.org/wiki/Stones_Throw_Records); [Wikipedia: Peanut Butter Wolf](https://en.wikipedia.org/wiki/Peanut_Butter_Wolf); [Medium: Stones Throw Records — Nurturing Underground Hip-Hop](https://jhallwrites.medium.com/stones-throw-records-nurturing-underground-hip-hop-8f7c8d396cdb); [Vice: 18 Years of Stones Throw Records](https://www.vice.com/en/article/peanut-butter-wolf-interview-edm-documentary-imprints/))
- **Brainfeeder**: Founded by Flying Lotus 2008. Even with label-controlled material on a Twitch stream (the MF DOOM tribute), the platform took it down. Brainfeeder ethos: experimental electronic + instrumental hip-hop, generally artist-friendly, but DMCA exposure is high. ([Wikipedia: Brainfeeder](https://en.wikipedia.org/wiki/Brainfeeder); [Stereofox: Brainfeeder Label Profile](https://www.stereofox.com/labels/brainfeeder/); [Norman Records: Label Watch — Brainfeeder](https://www.normanrecords.com/features/label-watch/brainfeeder); [Stones Throw: Faces on Film — Stones Throw x Brainfeeder](https://www.stonesthrow.com/news/faces-on-film-stones-throw-brainfeeder/))
- **Hyperdub**: South-East London label, Burial / Kode9 / Cooly G / etc. Per-artist policies; Hyperdub has historically been broadcast-friendly for radio attribution. ([Hyperdub: Contact](https://hyperdub.net/en-us/pages/contact); [Hyperdub on SoundCloud](https://soundcloud.com/hyperdub))
- **Awesome Tapes From Africa**: 50/50 royalty split, 6-month payment cycles, Fair Trade-ethos approach. Founder Brian Shimkovitz explicitly contrasts ATFA's structure with the local-fee-only practice it replaces. **Operator should research per-release for any Awesome Tapes catalog spin.** ([Wikipedia: Awesome Tapes From Africa](https://en.wikipedia.org/wiki/Awesome_Tapes_From_Africa); [Bizarre Culture: Interview with Brian Shimkovitz](https://bizarreculture.com/awesome-tapes-from-africa-an-interview-with-brian-shimkovitz/); [Awesome Tapes About](https://awesometapes.com/about/); [The Quietus: Africa In Your Cassette Decks](https://thequietus.com/interviews/awesome-tapes-from-africa-interview/); [Wave Farm: Overlooked — Awesome Tapes from Africa and Sahel Sounds](https://wavefarm.org/wf/archive/t05pt0))
- **Sahel Sounds**: 60% to artist on first album. The criticism of the label's framing (founder Christopher Kirkley's "gentleman explorer / rogue ethnomusicologist" Twitter bio has been called out by scholars as colonial-coded) is itself part of the public record the operator should know about. ([Wikipedia: Sahel Sounds](https://en.wikipedia.org/wiki/Sahel_Sounds); [Sahel Sounds: main site](https://sahelsounds.com/); [Sahel Sounds on Bandcamp](https://sahelsounds.bandcamp.com/); [The Conversation: Whose record is it anyway? Crate digging across Africa](https://theconversation.com/whose-record-is-it-anyway-musical-crate-digging-across-africa-83458); [Scroll.in: Crate digging — Why the Western obsession with old African music has a strain of neo-colonialism](https://scroll.in/magazine/849895/crate-digging-why-the-western-obsession-with-old-african-music-has-a-strain-of-neo-colonialism))

### §6.5 Per-artist research workflow before spin

The operator should institute a **10-minute pre-set research pass** for any new artist entering rotation:

- Search the artist's Bandcamp page for any "no broadcast" / "no remix" notes.
- Check artist's Instagram bio + recent posts for licensing posture.
- Search artist name + "DMCA" / "takedown" / "broadcast" — see if there's a public history of objections.
- Check the label's own broadcast policy (most indie labels publish nothing explicit; absence of policy is *not* permission, but it's a soft signal).
- Default-permissive for indie labels with public 50/50 splits (Stones Throw, Awesome Tapes); default-cautious for major-label catalog (UMG / Sony / Warner — even when the artist is small).

This research pass should produce a per-artist note in the operator's **Obsidian vault** (workspace CLAUDE.md § Obsidian) with `type: artist-policy` frontmatter, queryable from the council Logos API. The Hapax council already has the vault-frontmatter scanning machinery (`logos/data/vault_goals.py` pattern, see hapax-council CLAUDE.md § Orientation Panel) — this is a small extension.

---

## §7 Ethics of transformation — homage vs erasure

### §7.1 The Burial / Andy Stott axis

Burial's catalog is built on **anonymous vocal samples, processed beyond recognition**. Andy Stott similarly processes vocals into texture. The plunderphonic literature offers two competing readings:

- **Ethical-positive**: The transformation is so deep that the original artist's identity is preserved (anonymity protects them from association with the new context); the work is genuinely new; the source is a *texture*, not a *voice*.
- **Ethical-extractive**: The original artist's labor is taken without acknowledgment. The processing strips intent. The new work profits without the source benefiting.

Both readings are defensible and both are present in the scene's discourse. ([Wikipedia: Plunderphonics](https://en.wikipedia.org/wiki/Plunderphonics); [Springer: Sampling and Society — Intellectual Infringement and Digital Folk Music in Oswald's Plunderphonics](https://link.springer.com/chapter/10.1007/978-1-349-62374-7_7); [Vice: John Oswald Copyright Interview](https://www.vice.com/en/article/john-oswald-copyright-interview/); [Discogs Digs: Essential Plunderphonics](https://www.discogs.com/digs/music/essential-plunderphonics/); [DJBROADCAST: From Plunderphonics to Frankensampling](https://www.djbroadcast.net/article/98940/from-plunderphonics-to-frankensampling-a-brief-history-of-how-sampling-turned-to-theft); [Andrew Tholl: Plunderphonics — A Literature Review](http://www.andrewtholl.com/uploads/9/0/8/6/9086633/plunderphonics_literature_review.pdf))

### §7.2 The John Oswald *Plunderphonics* seizure

Oswald's 1989 *Plunderphonics* album **listed every source sample on the packaging** — full attribution. The album was free, distributed only to libraries and radio stations, explicitly non-commercial. Even with full attribution and no commerce, the Canadian Recording Industry Association (acting for CBS / Michael Jackson management) forced Oswald to **destroy 308 of the 1000 pressings and surrender all master tapes** (1990). ([econtact: Plunderphonics, or Audio Piracy as a Compositional Prerogative — Oswald's original essay](https://econtact.ca/16_4/oswald_plunderphonics.html); [Zamyn: Intellectual Property and the Politics of Plunderphonics](https://www.zamyn.org/programmes/seminars/seminar2/contexts/intellectual-property-and-the-politics-of-plunderphonics.html); [Melodigging: Plunderphonics genre](https://www.melodigging.com/genre/plunderphonics))

The lesson: even **maximally ethical** sampling-broadcast practice (full attribution, non-commercial, library-only distribution) is not protected from rights-holder action. The ethical practice is doing the *honorable thing* even though it does not provide legal cover.

### §7.3 Operator's HARDM principle generalizes

Operator's memory `project_hardm_anti_anthropomorphization` establishes that HARDM (Hapax's reverie/imagination surface) refuses face-iconography — no eyes, mouths, expressions. Raw signal-density on a grid. The principle is a **constitutional refusal of ventriloquism**.

This principle generalizes to vinyl-broadcast transformation: **the artist's voice is not yours to ventriloquize**. Heavy granular processing of a vocalist (vs. an instrumental) is ethically heavier than heavy processing of an instrument, because the voice is a *person*. The Burial / Andy Stott model — anonymous source, no identifiable individual — is the ethical version. Identifying a vocalist by name and then granularly destroying their delivery is the violating version.

Operationally: when the Evil Pet granular goes deep on a vocal track, the chyron should foreground **the original artist's name**, not the operator's processing. Attribution **counterweighs** transformation — the heavier the transformation, the louder the attribution must be.

### §7.4 The transformation-as-respect threshold

Pete Rock's posture from §2.1 ("keep the vibe of the original records just to show some respect musically") supplies a useful heuristic: **transformation is respectful when it preserves at least one structural property of the source that is recognizable to a listener familiar with the source**. If the operator chops a record so heavily that no one familiar with the original can recognize it, the transformation has crossed from quotation into theft-by-erasure.

For livestream practice: the operator should periodically **drop the transformation entirely** for 30–60 seconds in the middle of a heavily-processed spin, letting the source come through intact, then re-apply the processing. This is the equivalent of Dilla's "let the original tunes play out a few bars before flipping them" (§2.3) — structural acknowledgment within the work itself.

---

## §8 Gender and race in the broadcast practice

### §8.1 Producer-visibility crisis

USC Annenberg data: the rate of female music producers has fallen from 5% to 2% in the studied window. Studios remain heavily male-dominated; "young women were not especially welcome in male social spaces where technological knowledge is shared." This pattern reproduces in the livestream beat-scene, where the named producer-Twitch streams (Kenny Beats, JFK, etc.) are predominantly male. ([Madame Gandhi blog (Ebonie Smith Billboard guest column): Why Are Female Music Producers Everywhere, Yet So Invisible?](https://madamegandhi.blog/2018/03/01/ebonie-smith-why-are-female-music-producers-everywhere-yet-so-invisible-guest-column-billboard/); [Sounds So Beautiful: 14 female producers beat the drum for visibility and inclusion](https://soundssobeautiful.net/2022/06/18/female-producers-visibility/); [BPM Music Blog: 10 Powerhouse Female Producers to Watch For in 2023](https://blog.bpmmusic.io/news/10-powerhouse-female-producers-to-watch-for-in-2023/); [iHeart: 5 Female Hip-Hop Producers You Need To Know](https://www.iheart.com/content/2022-02-25-5-female-producers-you-need-to-know/); [Grammy: 15 Female & Nonbinary Producers To Know](https://www.grammy.com/news/female-producers-to-know-music-songwriters-engineers); [Stereofox: Women in Music — 9 Female Producers on the Challenges](https://www.stereofox.com/articles/women-in-music-female-producers-challenges/); [Grammy: Women In Hip-Hop — 7 Trailblazers Whose Behind-The-Scenes Efforts Define The Culture](https://www.grammy.com/news/women-behind-the-scenes-in-hip-hop-sylvia-rhone-sylvia-robinson-ethiopia-habtemariam))

For the operator's practice: the rotation should **track gender + identity composition** of artists spun. Not as a quota — as a **diagnostic**. If the operator's first quarter on-air is 95% male producers, that is signal about whose records are in the operator's crate, which is signal about whose records the operator's *digging context* surfaces. The data is actionable: it suggests where to dig next.

### §8.2 Crate-digging colonialism

The crate-digging tradition has a **documented colonial-extraction layer**: lifting beats from Indonesian / Brazilian / African records where the original artists never received royalties, where the labels sometimes never paid the artists at all, and where Western collectors' resale markets profit from records that the artist's family or community will never see a dollar from.

Specific critiques in the public record include:
- *Scroll.in* (2018): "Crate digging — Why the Western obsession with old African music has a strain of neo-colonialism." ([Scroll.in](https://scroll.in/magazine/849895/crate-digging-why-the-western-obsession-with-old-african-music-has-a-strain-of-neo-colonialism))
- *The Conversation* (2018): "Whose record is it anyway? Musical crate digging across Africa." Notes that some collector-label founders adopt explicitly colonial framing ("gentleman explorer, rogue ethnomusicologist"). ([The Conversation](https://theconversation.com/whose-record-is-it-anyway-musical-crate-digging-across-africa-83458))
- *The Conversation* (2018): "Somali songs reveal why musical crate digging is a form of cultural archaeology" — framing the practice as *recovery* when done with care, *plunder* when done without. ([The Conversation: Somali songs](https://theconversation.com/somali-songs-reveal-why-musical-crate-digging-is-a-form-of-cultural-archaeology-100285))
- Brazilian hip-hop's *Racionais MCs* tradition addresses colonial legacy explicitly — work like "Negro Drama" interrogates Brazil's racial / class structure as itself the subject matter of the music. ([International Journal of Communication: Negro Drama](https://ijoc.org/index.php/ijoc/article/view/21302); [Tandfonline: Putting mano to music — Brazilian rap](https://www.tandfonline.com/doi/abs/10.1080/1741191042000286211))
- Hip-hop scholarship: hip-hop's origins themselves are an *organic decolonization* practice. Diaspora music, made by people who were extracted from their homelands, recombining their cultural inheritance into new forms. ([Decolonization: HipHop's Origins as Organic Decolonization](https://decolonization.wordpress.com/2015/04/02/hiphops-origins-as-organic-decolonization/); [Fuller Studio: Crate-Digging through Culture — Hip Hop and Mission in Africa](https://fullerstudio.fuller.edu/crate-digging-through-culture-hip-hop-and-mission-in-africa-megan-meyers/))

For the vinyl-broadcast operator: when spinning a non-Western record, the attribution chyron should include **country of origin + label** in addition to artist + release. The economic-flow commitment (§5) should be checked specifically for non-Western artists — does the artist actually have a Bandcamp? If not, the operator should research a direct payment path (Patreon, GoFundMe, label-direct contact) before adding to rotation.

### §8.3 Diversity-curation models

NTS Radio (§3.2) and Dublab (§3.3) both have explicit curation programs around underrepresented voices. NTS founder Femi Adeyemi's framing — that the station was a response to a homogenous radio climate — is itself a useful operating principle for the operator's curation. Dublab's youth apprenticeship program (LA2050-funded) provides a model for the *educational extension* of the broadcast practice. ([LA2050: Dublab Radio Apprenticeship Program for High Schoolers](https://la2050.org/ideas/2024/dublab-radio-apprenticeship-program-for-high-schoolers))

---

## §9 Channel posture as ethical signal

### §9.1 The Description / About page

The channel's About page is the operator's **public licensing-posture statement**. Generic language ("Music streaming 24/7, hip-hop and jazz") is structurally weaker than specific framing ("Live DJ set / live mix performance, vinyl from operator's personal collection, 50/50 with the original artist where possible").

Recommended framing:

> LegomenaLive is a live DJ-set and live-remix broadcast by [operator]. All vinyl played comes from the operator's personal collection. Sets typically use heavy live processing (granular, time-stretch, layering). Where transformation is light, attribution is explicit; where transformation is heavy, attribution is louder. Tips are routed monthly to the original artists via Bandcamp; see the pinned post for the current month's allocation. Artists or labels who would prefer not to appear in rotation: please contact [email] and we will remove your work from the queue immediately and permanently.

This framing accomplishes four things at once: (a) declares the broadcast as performance rather than streaming-service, which is ethically and arguably legally stronger; (b) acknowledges the transformation-attribution tradeoff explicitly; (c) commits to economic flow; (d) provides a direct contact path that pre-empts DMCA escalation.

### §9.2 Tip-jar disclosure

Donation/tip flows should disclose **where the money goes** with each donation prompt. Streamlabs and similar tools support custom messaging on the donation overlay. A single line — "Tips this stream are routed monthly to artists spun, proportional to airtime; current month: $X across Y artists" — turns the tip from a charity-to-streamer transaction into a participation in the operator's economic-flow commitment.

### §9.3 Public ethics statement

Operator should publish a short, dated, versioned **Vinyl Broadcast Ethics Statement** on a stable URL. Version 1.0 can be ~500 words, covers: scope of practice, attribution commitment, economic-flow commitment, no-play list policy, takedown response posture, contact path. Updated when policy changes; old versions archived. This is the **transparency hygiene** that distinguishes a serious practice from a freeloading one.

A reasonable model for the format: NTS's freshdesk articles (one-page, plain-language, linked from main site) and Mixcloud's help-center copyright/licensing pages (matter-of-fact, declarative).

---

## §10 Good faith with rights-holders

### §10.1 The §512(f) sword and the moral floor

Parent doc §2.7 covers the legal mechanics of DMCA §512 takedown / counter-notification, including the *Lenz v. Universal Music Corp.* good-faith requirement: a rights holder must consider fair use *in good faith* before sending a §512 notice. The good-faith consideration "need not be searching or intensive" but must occur. ([U.S. Copyright Office §512 resources](https://www.copyright.gov/512/); [Vondran Legal: DMCA Bad Faith Bully cases](https://www.vondranlegal.com/federal-dmca-lawyer-bad-faith-lawsuit-17-usc-512f); [Neal Gerber: Ninth Circuit on good faith in DMCA notices](https://www.nge.com/news-insights/publication/client-alert-ninth-circuit-says-think-twice-before-sending-that-takedown-notice-under-dmca-be-sure-you-have-a-good-faith-belief-its-not-fair-use/); [Vondran Legal: Subjective Bad Faith in 512(f) claims](https://www.vondranlegal.com/ninth-circuit-512f-dmca-bad-faith-claims-require-evidence-of-subjective-state-of-mind); [Wake Forest Law Review: Deterring Abuse of the Copyright Takedown Regime](https://www.wakeforestlawreview.com/2011/11/deterring-abuse-of-the-copyright-takedown-regime-by-taking-misrepresentation-claims-seriously/); [SLU Law: Notice, Takedown, and the Good-Faith Standard](https://scholarship.law.slu.edu/context/plr/article/1173/viewcontent/PLR29_2_Wilson___Comment_.pdf); [DMLP: Responding to a DMCA Takedown Notice](http://www.dmlp.org/legal-guide/responding-dmca-takedown-notice-targeting-your-content); [Nolo: DMCA Takedown Notices and How to Respond](https://www.nolo.com/legal-encyclopedia/responding-dmca-takedown-notice.html); [Artist Rights Watch: DMCA Takedown Notices](http://www.artistrights.info/digital-millennium-copyright); [Wikipedia: DMCA](https://en.wikipedia.org/wiki/Digital_Millennium_Copyright_Act))

The **ethical floor**, separate from the legal mechanics, is:

1. **First DMCA on a track**: comply immediately. Do not counter-notice. Within 7 days, send a **direct outreach** to the rights holder via the labels' contact pages or the artist's social DMs: "I received a takedown on [track]. I removed it. I'd like to understand whether you'd prefer it stay off the channel permanently, or whether you'd like to discuss terms under which it could continue. I'm a single producer running [channel] from a personal vinyl collection; I treat the catalog respectfully."
2. **Outreach response: explicit no**: drop the artist from rotation **forever**. Add to the public no-play list. Note the date and the response.
3. **Outreach response: silence (≥30 days)**: drop the artist from rotation **silently** (no public no-play list addition; treat as default-cautious). Don't reach out again unless the artist or label initiates.
4. **Outreach response: yes / acceptable terms**: document the agreement (in the operator's Obsidian vault, dated, with link to the conversation), continue rotation.
5. **Repeat takedown on the same artist**: the operator's assumption was wrong about the rights-holder posture. Drop the artist permanently and add to the public no-play list.

This protocol is the operator's **moral floor**. The legal floor (parent doc §2.7) requires only takedown compliance; the moral floor requires *engagement*.

### §10.2 Communication channels

Most indie labels list a `contact@labelname.com` email; many list an Instagram/Twitter DM as primary. Some labels prefer Discord / Bandcamp messages. The operator should **assemble a contact-path note per label** in the Obsidian vault (`type: label-contact` frontmatter), so when the takedown comes the response path is already loaded.

### §10.3 What good-faith looks like from the rights-holder's perspective

A rights-holder who has issued a takedown is most reassured by:
- **Compliance speed** (removal within hours, not days)
- **Engagement** (outreach acknowledging the takedown, not silence)
- **No counter-notice on the first incident** (the legal counter-notice is structurally adversarial; even if the operator's use is defensible, counter-noticing escalates rather than resolves)
- **Public posture of respect** (the channel's About page already declared a posture; the takedown response should align with it)

### §10.4 The structural asymmetry

Rights holders have automated DMCA systems that can issue 1000s of takedowns per day; individual operators have hours per week to engage with each one. The asymmetry is permanent. The operator's response posture should account for this — *most takedowns will come from automated systems with no human at the other end*. Outreach in those cases will likely never reach a human. The operator should still attempt outreach (it costs little, occasionally reaches someone), but should not condition channel decisions on outreach response.

---

## §11 Concrete ethical commitments operator can adopt

### §11.1 This week (announce on channel)

1. **Live attribution floor** (§1, §4): on-screen now-playing chyron with artist + label + Bandcamp link, present for the entire spin. Implementation: per-set queue file + Hapax studio compositor Cairo overlay (parent council CLAUDE.md § Studio Compositor), 10 minutes of operator pre-set load time.
2. **Direct economic flow** (§1, §5): monthly tip-routed Bandcamp purchases proportional to airtime. Public ledger pinned. Implementation: per-spin metadata logging (already implicit in the MIDI Dispatch / set-list), monthly aggregation cron, batch Bandcamp purchase first Friday of month.
3. **Public no-play list and good-faith protocol** (§1, §6, §10): one paragraph on channel About + linked openly-editable list (gist or static page). Implementation: zero infrastructure, just a written commitment.

### §11.2 This month (build into the practice)

4. **Per-artist research note** (§6.5): 10-min pre-rotation research pass per new artist; result lands in Obsidian vault as `type: artist-policy` note. Long-term: query-able from Logos API; orientation panel surfaces "needs research" warning when a queued artist has no policy note.
5. **Transformation acknowledgment beats** (§7.4): periodic 30–60s drops of source-untouched playback within heavily-processed spins; chyron shifts to artist-foreground during these moments.
6. **Channel ethics statement v1.0** (§9.3): published, dated, versioned, linked from About. ~500 words.

### §11.3 This quarter (extend the practice)

7. **Diversity diagnostic** (§8.1): track gender / identity / region composition of rotation; quarterly retrospective on whether the dig context is producing a diverse rotation; report findings publicly.
8. **Non-Western artist payment-path research** (§8.2): for any rotation entry from outside US/UK/EU, dedicated research pass to confirm an artist-direct payment path exists; if not, defer rotation until a path is found.
9. **Open-source the no-play list and policy note schema** (§6.5, §11.1): publish the `type: artist-policy` schema as a small spec other beat-scene operators can adopt; share the no-play list format (it benefits artists most when other channels honor the same list).

### §11.4 Quarterly retrospective

10. **Public retrospective** every 90 days: artist-spin distribution, tip-allocation totals, takedown count + response, no-play additions, transformation-vs-attribution balance commentary. ~1000 words. Published as a dated post on the channel.

---

## §12 Open questions

1. **Lightning Network micropayments**: Has any beat-scene streamer adopted Bitcoin Lightning tipping with per-spin proportional routing? (Initial searches surface nothing definitive in the beat scene specifically — there is broader podcast-2.0 / "Value4Value" Lightning tipping practice, but no scene-specific adoption found in this research pass.) Worth a deeper investigation if the operator wants to be among the first.
2. **Real-time aggregate tip-disclosure to viewers**: "$X has been routed to artists this stream" — is anyone displaying this live? (Not surfaced in this research pass.) If not, the operator could be first; if so, the operator should adopt the existing convention.
3. **Per-set artist consent inventory**: How much consent-research-before-set is realistically sustainable? At one set per week, 10 min/artist, 12 artists/set = 2 hours of research per set. At a set per day, this scales painfully. Is there a tooling solution (LLM-summarized artist policy from socials/labels feeds, surfaced in Logos orientation panel) that could collapse the load?
4. **The aesthetic-vs-economic attribution tradeoff** (§3.1, §4.2): is there a position that does *less* on-screen attribution (preserving aesthetic mystique) while doing *more* economic-flow (Mixcloud-licensed broadcast + artist-direct tipping)? Both Boiler Room (cleared, low-attribution) and the operator's recommended position (uncleared-on-YouTube, high-attribution) are coherent. The Mixcloud option might be the third coherent position worth deeper exploration.
5. **HARDM-principle generalization across the stack** (§7.3): operator's anti-anthropomorphization invariant for HARDM has obvious extension to vinyl-broadcast (don't ventriloquize the artist). Does it extend further — to album-art display (the Hapax studio compositor's album-cover overlay)? Operator's preference: probably yes, but the precise rendering convention (when does showing an artist's photo become anthropomorphization?) is worth a separate research pass.
6. **The labor of curation** as itself an ethical good — does the broadcast practice acknowledge curation labor (the operator's, the original DJ tradition's, the diggers who supplied the operator's collection) sufficiently? Research not pursued in this dispatch but worth a future deepening.

---

## §13 Sources

### Practitioner interviews and primary scene press

#### Producer interviews
- [Tape Op: RZA on Wu-Tang's production](https://tapeop.com/interviews/163/rza)
- [NPR Fresh Air: 50 years of hip-hop, RZA](https://www.npr.org/2023/09/01/1197210646/fresh-air-celebrates-50-years-of-hip-hop-wu-tang-clans-rza)
- [unkut: The RZA Interview](https://unkut.com/2014/12/the-rza-the-unkut-interview/)
- [Acclaim: Origins, intricacies — RZA interview](https://acclaimmag.com/music/interview-rza/)
- [Ambrosia for Heads: RZA's controversial views on sample lawsuits](https://ambrosiaforheads.com/2015/03/rza-has-some-controversial-views-on-sample-lawsuits-in-2015-do-you-agree/)
- [MTV: RZA recalls being challenged to stop sampling](https://www.mtv.com/news/nsf8a6/rza-wu-tang-sampling)
- [Beat Making Videos: RZA on production style, Sampling, Growth & Musical Evolution](https://beatmakingvideos.com/video/interview/the-rza-on-his-change-in-production-style-sampling-growth-musical-evolution/)
- [Wikipedia: RZA](https://en.wikipedia.org/wiki/RZA)
- [HotNewHipHop: Pete Rock on sampling and crate-digging](https://www.hotnewhiphop.com/321011-pete-rock-explains-his-sampling-process-the-power-of-jazz-and-why-crate-digging-will-never-die-news)
- [HipHopDX: Pete Rock on the art of sampling](https://hiphopdx.com/news/id.15755/title.pete-rock-talks-the-art-of-sampling-names-his-three-favorite-productions)
- [Crate Kings: Pete Rock on sample clearance](https://cratekings.com/pete-rock-talks-about-sample-clearance-and-favorite-equipment/)
- [Hip Hop Golden Age: Crate Diggers — Pete Rock](https://hiphopgoldenage.com/crate-diggers-pete-rock/)
- [Okayplayer: Crate Digging With Pete Rock](https://www.okayplayer.com/news/video-crate-digging-with-pete-rock.html)
- [unkut: Pete Rock Interview](https://unkut.com/2008/04/pete-rock-the-unkut-interview/)
- [EARMILK: The Wire interviews Madlib](https://earmilk.com/2009/07/15/the-wire-interviews-madlib/)
- [Stones Throw: Sound Pieces — Madlib Interview](https://www.stonesthrow.com/news/sound-pieces-madlib-interview/)
- [The Quietus: The Strange World of Madlib](https://thequietus.com/articles/26665-madlib-madvillain-quasimoto-review)
- [Bandcamp Daily: Crate-Digging Depths of Madlib's Medicine Show](https://daily.bandcamp.com/lists/madlib-medicine-show-list)
- [Passion of the Weiss: The Madlib Mystique](https://www.passionweiss.com/2023/08/24/madlib-interview-la-weekly-2010/)
- [Bandcamp Daily: Knxwledge breaks down 1988](https://daily.bandcamp.com/features/knxwledge-1988-interview)
- [The Hundreds: A Conversation with Knxwledge](https://thehundreds.com/blogs/content/knxwledge-interview)
- [FACT: An interview with Stones Throw's Knxwledge](https://www.factmag.com/2015/05/31/knxwledge-interview/)
- [The FADER: Beat Construction — Knxwledge](https://www.thefader.com/2015/05/19/beat-construction-knxwledge)
- [Hypebeast: Knxwledge talks 1988](https://hypebeast.com/2020/4/knxwledge-1988-album-interview)
- [Ableton: Knxwledge — Staying in Go Mode](https://www.ableton.com/en/blog/knxwledge-staying-in-go-mode/)
- [DJBooth: Knxwledge has no idea](https://djbooth.net/features/2015-04-22-knxwledge-producer-interview/)
- [XLR8R: Rapper Proof — Knxwledge](https://xlr8r.com/features/rapper-proof-how-hardworking-la-beatmaker-knxwledge-became-the-most-known-unknown-producer-in-the-game/)
- [Acclaim: Knxwledge talks Hud Dreems](https://acclaimmag.com/music/interview-knxwledge/)
- [Stones Throw: Interview with Peanut Butter Wolf](https://www.stonesthrow.com/news/interview-pbw-archive/)
- [Wikipedia: Peanut Butter Wolf](https://en.wikipedia.org/wiki/Peanut_Butter_Wolf)
- [Vice: 18 Years of Stones Throw Records](https://www.vice.com/en/article/peanut-butter-wolf-interview-edm-documentary-imprints/)
- [Phoenix New Times: Peanut Butter Wolf on Stones Throw](https://www.phoenixnewtimes.com/music/peanut-butter-wolf-spins-the-history-of-his-stones-throw-records-6459497)

#### J Dilla and *Donuts*
- [Perfect Circuit: J Dilla's Donuts retrospective](https://www.perfectcircuit.com/signal/j-dilla-donuts)
- [SFA scholarship: Analysis of Sampling Techniques in Donuts](https://scholarworks.sfasu.edu/cgi/viewcontent.cgi?article=1211&context=etds)
- [The Babble: J Dilla & The Art of Sampling](https://thebabblejournal.com/issueone/jdillaartofsampling)
- [Stereovision: How J Dilla's Donuts Permanently Reshaped Hip-Hop Production](https://thestereovision.com/content/2022/6/18/how-j-dillas-donuts-permanently-reshaped-hip-hop-production)
- [Columbia Journal of Law & the Arts: A Case for Sampling Under Copyright Law](https://journals.library.columbia.edu/index.php/lawandarts/announcement/view/681)

#### Liner-notes / oral-history tradition
- [Amazon: Check the Technique (Coleman, Questlove fwd)](https://www.amazon.com/Check-Technique-Liner-Hip-Hop-Junkies/dp/0812977750)
- [Word Is Bond: Check the Technique Vol. 2 review](https://www.thewordisbond.com/check-technique-volume-2-liner-notes-hiphop-junkies-book-review/)
- [Critical Improv: When Beats Meet Critique — Documenting Hip-Hop Sampling as Critical Practice](https://www.criticalimprov.com/index.php/csieci/article/download/3027/3584?inline=1)

### Scene streaming and platform sources

#### Boiler Room
- [Music Ally: Boiler Room brings mixes to Apple Music](https://musically.com/2020/08/20/boiler-room-brings-mixes-to-apple-music-and-djs-get-paid/)
- [The FADER: Boiler Room partners with Apple Music](https://www.thefader.com/2020/08/19/boiler-room-partners-with-apple-music-to-bring-its-mixes-to-the-platform)
- [5 Magazine: Boiler Room Is Changing](https://5mag.net/features/boiler-room-is-changing/)
- [Wikipedia: Boiler Room](https://en.wikipedia.org/wiki/Boiler_Room_(music_broadcaster))
- [Reprtoir: The Boiler Room Model and Current State of DJ Livestream Sector](https://www.reprtoir.com/blog/electronic-music-boiler-room)
- [DJ TechTools: Promoters paying Boiler Room licensing fees for branded parties](https://djtechtools.com/2019/09/17/promoters-clubs-paying-boiler-room-licensing-fees-for-non-broadcast-branded-parties/)

#### NTS Radio
- [NTS About](https://www.nts.live/about)
- [NTS: Licensing and Royalty Fees](https://ntslive.freshdesk.com/support/solutions/articles/77000586376-licensing-and-royalty-fees)
- [Music Business Worldwide: NTS founder interview](https://www.musicbusinessworldwide.com/we-are-not-just-a-digital-utensil-for-listening-to-music/)
- [Mixmag: An oral history of NTS Radio](https://mixmag.net/feature/nts-radio-oral-history)
- [Wikipedia: NTS Radio](https://en.wikipedia.org/wiki/NTS_Radio)
- [NTS: Where do NTS Supporter Funds Go](https://ntslive.freshdesk.com/support/solutions/articles/77000570070-where-do-nts-supporter-funds-go-)
- [NTS Release Agreement](https://www.nts.live/release-agreement)

#### Dublab
- [Wikipedia: Dublab](https://en.wikipedia.org/wiki/Dublab)
- [Dublab About](https://www.dublab.com/aboutdetail)
- [The FADER: At 25, Dublab is still the gold standard](https://www.thefader.com/2024/12/12/dublab-online-radio-station-25-anniversary-interview)
- [MusicTech: Dublab still the champion of independent online radio](https://musictech.com/features/interviews/dublab-online-radio-25-years/)
- [Beatportal: Future Roots Forever — Dublab](https://www.beatportal.com/articles/313517-future-roots-forever-how-las-dublab-revolutionized-online-community-radio)
- [LA2050: Dublab Radio Apprenticeship Program](https://la2050.org/ideas/2024/dublab-radio-apprenticeship-program-for-high-schoolers)

#### Worldwide FM / Gilles Peterson
- [Wikipedia: Gilles Peterson](https://en.wikipedia.org/wiki/Gilles_Peterson)
- [Wikipedia: Worldwide FM](https://en.wikipedia.org/wiki/Worldwide_FM)
- [Worldwide FM About](https://www.worldwidefm.net/)
- [Gilles Peterson Worldwide on Mixcloud](https://www.mixcloud.com/gillespeterson/)

#### Twitch / Kenny Beats
- [Twitch: Kenny Beats channel](https://www.twitch.tv/kennybeats)
- [La Tonique: Kenny Beats, Twitch and the Evolving Music Industry](https://www.latonique.news/articles/kenny-beats-twitch-and-the-evolving-music-industry)
- [Bloomberg: Twitch's streaming boom is jolting the music industry](https://www.bloomberg.com/news/articles/2020-06-18/twitch-s-streaming-boom-is-jolting-the-music-industry)
- [Lucid Monday: Matt Zara wins $10k from Kenny Beats' Battle](https://lucidmonday.com/blog/matt-zara-wins-10k-from-kenny-beats-battle-and-a-mix-from-tde-engineer-mixedbyali)
- [Twitch: DMCA & Copyright FAQs](https://help.twitch.tv/s/article/dmca-and-copyright-faqs?language=en_US)
- [Twitch: DJ Program FAQ](https://help.twitch.tv/s/article/dj-program-faq?language=en_US)
- [Twitch: Music Reporting Process](https://legal.twitch.com/en/legal/dmca-guidelines/music-reporting-process/)
- [Twitch: Music Guidelines](https://legal.twitch.com/en/legal/music/)
- [Twitch Blog: Music-Related Copyright Claims](https://blog.twitch.tv/en/2020/11/11/music-related-copyright-claims-and-twitch/)
- [Twitch: DJ Program Terms](https://legal.twitch.com/en/legal/dj-program-terms/)
- [Mixmag: Twitch launches DJ payment update](https://mixmag.net/read/twitch-djs-pay-revenue-to-record-labels-news)
- [Exron Music: Twitch DJ Program reveals streaming without DMCA strikes](https://exronmusic.com/2024/07/27/twitch-dj-program-reveals-streaming-without-dmca-strikes/)
- [Twitch Music Cleared Carrd](https://twitchmusic.carrd.co/)

#### Mixcloud
- [Mixcloud: Creator Subscriptions revenue model](https://help.mixcloud.com/hc/en-us/articles/360004031220-How-does-the-Creator-Subscriptions-revenue-model-work)
- [Mixcloud: How we pay creators and why we do it](https://www.mixcloud.com/mixcloud/posts/how-we-pay-creators-and-why-we-do-it/)
- [Mixcloud: Is Mixcloud licensed to play copyrighted music](https://help.mixcloud.com/hc/en-us/articles/360004185159-Is-Mixcloud-licensed-to-play-copyrighted-music)
- [DJ TechTools: Mixcloud founder on what DJs need to know about copyright](https://djtechtools.com/amp/2020/11/18/mixcloud-founder-heres-what-djs-need-to-know-about-music-copyright/)
- [FACT: Mixcloud Select royalty model breakdown](https://www.factmag.com/2019/06/14/mixcloud-select-royalties/)
- [Mixcloud Medium: How audio creators can make money with Mixcloud Select](https://medium.com/mixcloud/how-audio-creators-can-make-money-with-mixcloud-select-breaking-down-the-model-34cd23bf3182)

#### Bandcamp
- [Bandcamp For Artists](https://bandcamp.com/artists)
- [Bandcamp Fridays 2025 announcement](https://blog.bandcamp.com/2025/03/04/why-bandcamp-fridays-matter-even-if-youre-not-releasing-new-music/)
- [Bandcamp Friday Help](https://get.bandcamp.help/hc/en-us/articles/23006342800407-Bandcamp-Friday-Help)
- [Wikipedia: Bandcamp](https://en.wikipedia.org/wiki/Bandcamp)
- [Okayplayer: Independent Artists to Support on Bandcamp Friday](https://www.okayplayer.com/originals/20-independent-artists-to-support-on-bandcamp-friday-october-edition.html)
- [Bandcamp Daily: Today is Bandcamp Friday](https://daily.bandcamp.com/features/bandcamp-fridays)
- [Forthe: Bandcamp Friday is Back](https://forthe.org/arts-culture/bandcamp-friday-is-back/)

### Track-ID / now-playing tooling
- [Now Playing App](https://www.nowplayingapp.com/)
- [Serato Now Playing Twitch extension](https://support.serato.com/hc/en-us/articles/360001991976-Using-the-Serato-Now-Playing-Twitch-extension)
- [whats-now-playing on GitHub](https://github.com/whatsnowplaying/whats-now-playing)
- [erikrichardlarson/unbox on GitHub](https://github.com/erikrichardlarson/unbox)
- [Bombe/obs-dj-overlay on GitHub](https://github.com/Bombe/obs-dj-overlay)
- [DJ TechTools: Prolink Tools pulls CDJ data](https://djtechtools.com/2021/01/25/prolink-tools-pulls-cdj-data-to-enhance-dj-sets-share-track-info-into-live-streams/)
- [DJ Cavon: Serato adds Twitch extension for Track ID](https://djcavon.com/serato-adds-twitch-extension-for-track-id/)
- [Digital DJ Tips: Serato Launches Free DJ Visuals & Twitch Extension](https://www.digitaldjtips.com/serato-twitch-visuals-extension/)
- [Engine DJ Community: Track ID bot for Twitch](https://community.enginedj.com/t/track-id-bot-for-twitch/38895)
- [Pioneer DJ forum: Currently played track in Rekordbox to OBS](https://forums.pioneerdj.com/hc/en-us/community/posts/360059165691-Currently-played-track-in-Rekordbox-as-text-to-OBS-in-live-stream)

### Labels and indie distribution

#### Stones Throw / Brainfeeder
- [Wikipedia: Stones Throw Records](https://en.wikipedia.org/wiki/Stones_Throw_Records)
- [Medium: Stones Throw Records — Nurturing Underground Hip-Hop](https://jhallwrites.medium.com/stones-throw-records-nurturing-underground-hip-hop-8f7c8d396cdb)
- [Stones Throw History](https://www.stonesthrow.com/about/)
- [Wikipedia: Brainfeeder](https://en.wikipedia.org/wiki/Brainfeeder)
- [Stereofox: Brainfeeder Label Profile](https://www.stereofox.com/labels/brainfeeder/)
- [Norman Records: Label Watch — Brainfeeder](https://www.normanrecords.com/features/label-watch/brainfeeder)
- [Stones Throw: Faces on Film — Stones Throw x Brainfeeder](https://www.stonesthrow.com/news/faces-on-film-stones-throw-brainfeeder/)
- [Dexerto: MF DOOM memorial stream shut down](https://www.dexerto.com/entertainment/fans-furious-as-mf-doom-memorial-stream-is-shut-down-over-rumored-dmca-issues-1488103/)
- [Game Rant: Twitch takes down MF Doom Tribute stream hosted by Brainfeeder](https://gamerant.com/twitch-mf-doom-tribute-stream-dmca-takedown/)
- [Hyperdub: Contact](https://hyperdub.net/en-us/pages/contact)
- [Hyperdub on SoundCloud](https://soundcloud.com/hyperdub)

#### Awesome Tapes / Sahel Sounds
- [Wikipedia: Awesome Tapes From Africa](https://en.wikipedia.org/wiki/Awesome_Tapes_From_Africa)
- [Bizarre Culture: Brian Shimkovitz interview](https://bizarreculture.com/awesome-tapes-from-africa-an-interview-with-brian-shimkovitz/)
- [Awesome Tapes About](https://awesometapes.com/about/)
- [The Quietus: Africa In Your Cassette Decks](https://thequietus.com/interviews/awesome-tapes-from-africa-interview/)
- [Skiddle: Awesome Tapes From Africa Interview — Eyes Of The World](https://www.skiddle.com/news/all/Awesome-Tapes-From-Africa-Interview-Eyes-Of-The-World/28964/)
- [Wikipedia: Sahel Sounds](https://en.wikipedia.org/wiki/Sahel_Sounds)
- [Sahel Sounds main site](https://sahelsounds.com/)
- [Sahel Sounds on Bandcamp](https://sahelsounds.bandcamp.com/)
- [Norman Records: Sahel Sounds catalog](https://www.normanrecords.com/label/7184-sahel-sounds)
- [Wave Farm: Overlooked — Awesome Tapes from Africa and Sahel Sounds](https://wavefarm.org/wf/archive/t05pt0)

#### Lofi Girl
- [TechCrunch: Lofi Girl two-year-long stream takedown](https://techcrunch.com/2022/07/11/lofi-girl-takedown-youtube-music-stream-dmca/)
- [NPR: Lofi Girl disappeared from YouTube](https://www.npr.org/2022/07/16/1111588405/lofi-girl-youtube-stream-copyright)
- [The FADER: After the Lofi Girl takedown](https://www.thefader.com/2022/07/15/after-the-lofi-girl-takedown-can-youtube-protect-users-from-copyright-claim-abuse)
- [NBC News: YouTube reinstating Lofi Girl streams](https://www.nbcnews.com/pop-culture/pop-culture-news/youtube-says-will-reinstate-lofi-girls-live-streams-false-copyright-cl-rcna37613)
- [Music Ally: Copyright claim takes down Lofi Girl YouTube streams](https://musically.com/2022/07/12/copyright-claim-takes-down-lofi-girls-youtube-music-streams/)
- [The Hustle: Lofi Girl vs. YouTube's copyright problem](https://thehustle.co/07192022-lofi-girl)
- [Soundstripe: Lofi Girl Saga and protection against false claims](https://www.soundstripe.com/blogs/lofi-girl-what-creators-can-do-to-protect-against-copyright-claims)

### Sampling-ethics scholarship
- [Wikipedia: Bridgeport Music v. Dimension Films](https://en.wikipedia.org/wiki/Bridgeport_Music,_Inc._v._Dimension_Films)
- [DePaul Law Review: How the Sixth Circuit Missed a Beat on Digital Music Sampling](https://via.library.depaul.edu/cgi/viewcontent.cgi?httpsredir=1&article=1343&context=law-review)
- [Indiana Law Journal: Mueller on Bridgeport and de minimis](https://ilj.law.indiana.edu/articles/81/81_1_Mueller.pdf)
- [escholarship: From Mozart to Hip-Hop — Bridgeport's Impact](https://escholarship.org/content/qt61k2v6tz/qt61k2v6tz_noSplash_6d0d0e48df9240ff1581efded0d807c8.pdf)
- [GW Law MCIR: Bridgeport Music v. Dimension Films](https://blogs.law.gwu.edu/mcir/case/bridgeport-music-v-dimension-films-et-al/)
- [Foundations of Law and Society: Bridgeport Music v. Dimension Films — The Battle of Music Sampling](https://foundationsoflawandsociety.wordpress.com/2018/12/07/bridgeport-music-v-dimension-films-the-battle-of-music-sampling/)
- [CUNY: Sampling in Hip-Hop / aesthetics of community](https://academicworks.cuny.edu/cgi/viewcontent.cgi?article=1029&context=le_etds)
- [UBC: Sampling in Hip-Hop / aesthetics analysis](https://open.library.ubc.ca/media/stream/pdf/24/1.0450749/4)
- [WUSTL Open Scholarship: Sampling in Hip-Hop — Creative Genius or Total Flop](https://openscholarship.wustl.edu/cgi/viewcontent.cgi?article=1060&context=undergrad_etd)
- [Academia.edu: What Makes A Good Hip-Hop Sample?](https://www.academia.edu/35100796/What_Makes_A_Good_Hip_Hop_Sample)

### Plunderphonics and transformation ethics
- [Wikipedia: Plunderphonics](https://en.wikipedia.org/wiki/Plunderphonics)
- [Springer: Sampling and Society — Intellectual Infringement and Digital Folk Music in Oswald's Plunderphonics](https://link.springer.com/chapter/10.1007/978-1-349-62374-7_7)
- [Vice: John Oswald Copyright Interview](https://www.vice.com/en/article/john-oswald-copyright-interview/)
- [Discogs Digs: Essential Plunderphonics](https://www.discogs.com/digs/music/essential-plunderphonics/)
- [DJBROADCAST: From Plunderphonics to Frankensampling](https://www.djbroadcast.net/article/98940/from-plunderphonics-to-frankensampling-a-brief-history-of-how-sampling-turned-to-theft)
- [Andrew Tholl: Plunderphonics — A Literature Review](http://www.andrewtholl.com/uploads/9/0/8/6/9086633/plunderphonics_literature_review.pdf)
- [Melodigging: Plunderphonics genre](https://www.melodigging.com/genre/plunderphonics)
- [Micro Genre Music: What is Plunderphonics?](https://microgenremusic.com/articles/what-is-plunderphonics/)
- [econtact: Oswald's original Plunderphonics essay](https://econtact.ca/16_4/oswald_plunderphonics.html)
- [Zamyn: Intellectual Property and the Politics of Plunderphonics](https://www.zamyn.org/programmes/seminars/seminar2/contexts/intellectual-property-and-the-politics-of-plunderphonics.html)

### Race, gender, colonial appropriation
- [Madame Gandhi blog (Ebonie Smith Billboard guest column): Why Are Female Music Producers Everywhere, Yet So Invisible?](https://madamegandhi.blog/2018/03/01/ebonie-smith-why-are-female-music-producers-everywhere-yet-so-invisible-guest-column-billboard/)
- [Sounds So Beautiful: 14 female producers beat the drum for visibility and inclusion](https://soundssobeautiful.net/2022/06/18/female-producers-visibility/)
- [BPM Music Blog: 10 Powerhouse Female Producers to Watch For in 2023](https://blog.bpmmusic.io/news/10-powerhouse-female-producers-to-watch-for-in-2023/)
- [iHeart: 5 Female Hip-Hop Producers You Need To Know](https://www.iheart.com/content/2022-02-25-5-female-producers-you-need-to-know/)
- [Grammy: 15 Female & Nonbinary Producers To Know](https://www.grammy.com/news/female-producers-to-know-music-songwriters-engineers)
- [Grammy: Women In Hip-Hop Behind the Scenes](https://www.grammy.com/news/women-behind-the-scenes-in-hip-hop-sylvia-rhone-sylvia-robinson-ethiopia-habtemariam)
- [Stereofox: Women in Music — 9 Female Producers on the Challenges](https://www.stereofox.com/articles/women-in-music-female-producers-challenges/)
- [SOHH: Hip-Hop's Most Influential Female Producers](https://www.sohh.com/hip-hops-most-influential-female-producers/)
- [The Conversation: Whose record is it anyway? Crate digging across Africa](https://theconversation.com/whose-record-is-it-anyway-musical-crate-digging-across-africa-83458)
- [Scroll.in: Crate digging — neo-colonialism in Western African vinyl obsession](https://scroll.in/magazine/849895/crate-digging-why-the-western-obsession-with-old-african-music-has-a-strain-of-neo-colonialism)
- [The Conversation: Somali songs and crate digging as cultural archaeology](https://theconversation.com/somali-songs-reveal-why-musical-crate-digging-is-a-form-of-cultural-archaeology-100285)
- [International Journal of Communication: Negro Drama — Beyond the Colonial Family Romance in Brazilian Hip-Hop](https://ijoc.org/index.php/ijoc/article/view/21302)
- [Tandfonline: Putting mano to music — Brazilian rap and race mediation](https://www.tandfonline.com/doi/abs/10.1080/1741191042000286211)
- [Decolonization: HipHop's Origins as Organic Decolonization](https://decolonization.wordpress.com/2015/04/02/hiphops-origins-as-organic-decolonization/)
- [Fuller Studio: Crate-Digging through Culture — Hip Hop and Mission in Africa](https://fullerstudio.fuller.edu/crate-digging-through-culture-hip-hop-and-mission-in-africa-megan-meyers/)

### DMCA / good-faith / takedown response
- [U.S. Copyright Office §512 resources](https://www.copyright.gov/512/)
- [Vondran Legal: DMCA Bad Faith Bully cases](https://www.vondranlegal.com/federal-dmca-lawyer-bad-faith-lawsuit-17-usc-512f)
- [Neal Gerber Eisenberg: Ninth Circuit on good faith in DMCA notices](https://www.nge.com/news-insights/publication/client-alert-ninth-circuit-says-think-twice-before-sending-that-takedown-notice-under-dmca-be-sure-you-have-a-good-faith-belief-its-not-fair-use/)
- [Vondran Legal: Subjective Bad Faith in 512(f) claims](https://www.vondranlegal.com/ninth-circuit-512f-dmca-bad-faith-claims-require-evidence-of-subjective-state-of-mind)
- [Wake Forest Law Review: Deterring Abuse of the Copyright Takedown Regime](https://www.wakeforestlawreview.com/2011/11/deterring-abuse-of-the-copyright-takedown-regime-by-taking-misrepresentation-claims-seriously/)
- [SLU Law: Notice, Takedown, and the Good-Faith Standard](https://scholarship.law.slu.edu/context/plr/article/1173/viewcontent/PLR29_2_Wilson___Comment_.pdf)
- [DMLP: Responding to a DMCA Takedown Notice](http://www.dmlp.org/legal-guide/responding-dmca-takedown-notice-targeting-your-content)
- [Nolo: DMCA Takedown Notices and How to Respond](https://www.nolo.com/legal-encyclopedia/responding-dmca-takedown-notice.html)
- [Artist Rights Watch: DMCA Takedown Notices](http://www.artistrights.info/digital-millennium-copyright)
- [Wikipedia: Digital Millennium Copyright Act](https://en.wikipedia.org/wiki/Digital_Millennium_Copyright_Act)

### Prince / Wu-Tang rights-holder posture
- [Creative Commons: Recap of copyright issues surrounding Prince's estate](https://creativecommons.org/2016/05/23/controversy-recap-issues-surrounding-copyright-princes-estate/)
- [WHGC Law: Prince and the Copyright Revolution Part 1](https://www.whgclaw.com/publications-archive/prince-and-the-copyright-revolution-part-1/)
- [Consequence: Prince estate sells nearly half of rights](https://consequence.net/2021/07/prince-estate-sells-master-recordings-publishing-name-likeness/)
- [Morgan Lewis: Protecting Art Through Trade Secrets — Wu-Tang ruling](https://www.morganlewis.com/pubs/2025/10/protecting-art-through-trade-secrets-wu-tang-clan-ruling-opens-the-possibility)
- [Griffith Hack: When copyright collides with a vision — Wu-Tang's Shaolin](https://www.griffithhack.com/insights/publications/when-copyright-collides-with-a-vision-the-tale-of-wu-tang-clans-once-upon-a-time-in-shaolin/)
- [Complex: RZA files $2M lawsuit against Wu-Tang bootleggers](https://www.complex.com/music/a/cmplxtara-mahadevan/rza-files-2-million-lawsuit-wu-tang-bootleggers-trademark-infringement)
- [DJ Mag: RZA sells rights to 50% of his songwriting and production credits](https://djmag.com/news/wu-tang-clan-s-rza-sells-rights-50-his-songwriting-and-production-credits)
- [NPR: U.S. Government Sells Wu-Tang Clan Album Once Owned By Martin Shkreli](https://www.npr.org/2021/07/27/1021284593/martin-shkreli-wu-tang-clan-album-sold)

### Producer revenue / monetization
- [DJ Mag: How producers can get paid through streaming services](https://djmag.com/longreads/how-producers-can-get-paid-through-streaming-services)
- [Ari's Take: Turn Your Fans Into Paying Subscribers](https://aristake.com/turn-your-fans-into-paying-subscribers-with-this-platform/)
- [Cable Free Guitar: 9 Musician Income Streams in 2025](https://www.cablefreeguitar.com/blogs/performance-without-limits/9-musician-income-streams)
- [DJWORX: Where DJs are making money now](https://djworx.com/where-djs-are-making-money-now/)
- [DJ TechTools: The Basics of DJ Copyright Laws](https://djtechtools.com/2017/06/05/basics-dj-copyright-laws/)
- [Quora: How to purchase a streaming license for DJ sets](https://www.quora.com/How-do-I-purchase-a-license-so-I-can-stream-DJ-sets-online-Facebook-Live-YouTube-etc-There-are-multiple-companies-that-stream-Boiler-Room-Mixmag-how-do-I-do-that-as-a-normal-person)
