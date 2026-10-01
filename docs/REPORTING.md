# Reporting: what each program actually needs, and the PDF templates Thicket should generate

Research note, September 2026. Pilot context: a farm near Ithaca, NY (Tompkins County). Every claim below is tied to a source in [reporting-sources.md](reporting-sources.md). Where a program has no fixed template, this document says so and describes what the reviewer looks at instead.

Short version: none of these programs has a slot labeled "acoustic monitoring report". NRCS and NY AEM run on identifiers, dates, maps, photos and a planner's signature; acoustic evidence fits as a dated field log plus a bird-presence annex. Certifications want the land manager's records and let their own staff do the biology. Credit standards are the only place a structured monitoring report with baseline, sampling design, QA/QC and uncertainty is a hard requirement, and even there acoustics is accepted as a data source only when the standard's data rules (digital, metadata, validated identifications, replicable protocol) are met.

## 0. What Thicket can put in a report today

From `shared/api.schema.json` and `backend/thicket/services/exports.py`:

| Object | Fields Thicket already holds |
|---|---|
| RecordingInfo | filename, checksum_sha256, byte_size, format, content_type, duration_seconds, sample_rate_hz, bit_depth, channels, captured_at, timezone, latitude, longitude, site_name, recorder_type, notes |
| AnalysisSettings | decision_threshold, raw_threshold, hop_seconds, merge_gap_seconds, location_filter, location_filter_threshold, requested_models |
| ModelRun | model, version, adapter, model_sha256, configuration, window_seconds, hop_seconds, raw_threshold, n_windows, runtime_ms, taxa, experimental |
| DetectionEvent | id, taxon, common_name, scientific_name, start_seconds, end_seconds, max_confidence, mean_confidence, n_windows, plausibility, review_status, reviewed_label, review_note, detected_* (model label), counted_in_metrics, contributing_detection_ids |
| SpeciesSummary | detection_event_count, raw_detection_count, first/last_detection_seconds, total_event_duration_seconds, max/mean_confidence, plausibility |
| Metrics | species_richness, shannon_index, pielou_evenness, simpson_diversity, total_detection_events, events_per_minute, dominant_species, events_by_taxon, basis |
| AcousticIndices | ACI, ADI, AEI, BI, NDSI, spectral_entropy, temporal_entropy |
| QualityReport | score, status, peak_dbfs, rms_dbfs, clipping_fraction, silence_fraction, low_frequency_energy_fraction, speech_detected, checks[], warnings[] |
| Analysis | id, software_version, schema_version, created_at, completed_at, stage_timings_ms, warnings |
| Model cards | docs/model-cards/*.md (BirdNET v2.4, QC head v1, frog and insect head) |

Not built yet (spec Release D): sites, recorder deployments, protocols, multi-recording trends. Until those objects exist, deployment metadata (recorder make, height, schedule, weather) must be user-entered on the report form. The schema in section 7 treats them that way.

## 1. USDA NRCS EQIP and CSP

### Who reviews it

The NRCS field office (district conservationist and planner), with a Level 3 or higher certified planner countersigning the environmental evaluation, and an NRCS approving official releasing payment. A Technical Service Provider (TSP) may certify practice completion on NRCS's behalf. Ranking is done in CART (Conservation Assessment Ranking Tool) by NRCS staff, not by the producer.

### What is actually required (template vs narrative)

NRCS is form-driven. The producer never submits a free-form monitoring report. The documents that matter:

| Document | Who fills it | Fields a reviewer expects |
|---|---|---|
| NRCS-CPA-1200 Conservation Program Application | producer | applicant, program, land (farm/tract), eligibility |
| NRCS-CPA-1202 Conservation Program Contract and Appendix | NRCS + producer | contract number, schedule of operations (practice, item, planned amount, unit, year) |
| NRCS-CPA-52 Environmental Evaluation Worksheet | NRCS planner | A Client Name; B Conservation Plan ID; C Identification # (farm, tract, field); program authority; D objectives; E need for action; F resource concerns and benchmark conditions by SWAPAE (Soil, Water, Air, Plants, Animals, Energy, Human); G special environmental concerns (15 items incl. Endangered and Threatened Species, Migratory Birds / Bald and Golden Eagle Protection Act, Riparian Area, Wetlands, Invasive Species); H alternatives; I effects; L mitigation; M preferred alternative; O planner signatures; P to S NEPA finding signed by the Responsible Federal Official |
| Practice standard + state Implementation Requirements (job sheet) | NRCS planner writes, producer follows | practice code, purpose, criteria, plans and specifications, operation and maintenance |
| CSP enhancement sheet with supplement | producer keeps, NRCS verifies | Participant Name, Contract Number, Total Amount Applied, Fiscal Year Completed, NRCS Technical Adequacy Signature and Date; for E645D also Existing WHEG score, Planned Post Implementation WHEG score, Post Implementation WHEG score |
| NRCS-CPA-1245 Practice Approval and Payment Application | producer certifies, NRCS approves | header: Participant, Program and Contract Number, County and State, Fund Code, Watershed, Payment Application Number. Table: Contract Item, Practice, Inspection Date, Practice Completion, Planned Amount, Applied Amount, Units, Cost Per Unit, Cost Share %, Method, Payment Cap Amount, Amount Earned. Certification text: "Practice(s) performed to the extent shown above and meets program requirements." Participant certifies the information is true and agrees to maintain the practice for its service life |
| TSP Practice Completion Form (template 2, 2025) | TSP | Name as shown on NRCS Contract, Contract Number, Practice Code and Payment Scenario, CIN (contract item number), TSP Service Amount (CIN units), Practice Certification Date, attachments "including but not limited to maps, photos, or as-builts" |

Certification is "based on certification that NRCS standards and specifications have been met" (EQIP CIC Appendix). The verification methods NRCS uses are "site visits, local documentation reviews (such as producers' receipts, invoices, or proof of supply purchase), or engineering evaluations" (USDA OIG audit 10601-0005-31). The case file must tie every practice to "field, tract, and farm number" and the certifier must "sign and date a certification statement or appropriate program payment form that the practice meets NRCS standards and specifications"; for annual management practices (like 645 or 528) this "may be documented in the case file assistance notes, conservation plan, or program payment forms" (NRCS practice documentation guidance, Missouri eFOTG). Producers must retain records "for a period of three (3) full years after completion" (CPA-1202 appendix). Farm, tract and field numbers come from FSA (form FSA-156EZ and farm maps on farmers.gov), not from NRCS.

### Wildlife practices and enhancements relevant to a NY farm

Core wildlife practices on the FY25 EQIP wildlife list: 327 Conservation Cover, 390 Riparian Herbaceous Cover, 391 Riparian Forest Buffer, 420 Wildlife Habitat Planting, 422 Hedgerow Planting, 472 Access Control, 643 Restoration of Rare or Declining Natural Communities, 644 Wetland Wildlife Habitat Management, 645 Upland Wildlife Habitat Management, 647 Early Successional Habitat Development/Management, 649 Structures for Wildlife, 657/658/659 wetland restoration, creation, enhancement. Secondary: 314, 315, 338 Prescribed Burning, 382 Fence, 386 Field Border, 528 Prescribed Grazing (via 512/528 enhancements), 666 Forest Stand Improvement.

Practice 645 (2025 redline, retitled Wildlife Habitat Management): "A habitat evaluation ... shall be used to identify habitat-limiting factors"; "Complete monitoring activities in accordance with ... state developed monitoring protocols"; plans "prepared by persons with adequate training in the fields of wildlife management, biology or ecology"; O&M: "evaluate habitat conditions on a regular basis".

CSP enhancements with real documentation hooks:

| Code | Title | What the participant must keep and hand in |
|---|---|---|
| E645D | Enhanced Wildlife Habitat Management for Upland Landscapes | Wildlife Habitat Management Plan supplement (activities, locations, quantities, timing); field log with "Date/time of each field visit and document any required monitoring activities from the supplement"; "Digital photographs to document habitat"; NRCS calculates existing and post WHEG scores (post must be 0.6 or higher, or +0.1 over a baseline above 0.5) |
| E645A | Reduction of attractants to human-subsidized predators | field log with mapped attractant locations, removal dates, before/after photos |
| E645B, E645C | Manage shrub thickets; Edge feathering for wildlife cover | log, dates, photos (same pattern) |
| E666R | Forest songbird habitat maintenance | "During the bird breeding season, a trained forestry or wildlife specialist will conduct a bird census according to protocols adopted by the respective state's wildlife management agency"; participant provides "dates that inspection was conducted, methods used, reports on bird surveys and habitat monitoring, photos, and a map showing bird monitoring points" |
| E528N | Improved grazing management through monitoring activities | pasture/herd in/out records, 528 Trend worksheet, forage utilization job sheet, "Assessment Sheets with all field notes and locations" |
| E528D, E528E, E511B, E390B, E391C, E386E, E327C, E328L | grazing, harvest, buffer and cover enhancements for wildlife | dated records and photos per the enhancement sheet; no species data asked for |

Other items: the Wildlife Habitat Evaluation Guide (WHEG) is an NRCS-staff habitat scoring sheet "completed during field visits" that scores vegetation structure and cover, not wildlife observations. CART ranks applications against "Terrestrial Habitat (Terrestrial habitat for wildlife and invertebrates)" and "Aquatic Habitat (Aquatic habitat for fish and other organisms)" using client input, planner observation, procedural tools and predictive models compared to planning criteria thresholds; the NY FY26 CSP ranking questions carry no wildlife monitoring question at all. Working Lands for Wildlife (Northern Bobwhite framework) states that outcome monitoring "will be accomplished by Quail Forever partner staff in cooperation with the National Bobwhite Technical Committee"; producers are not expected to collect bird data. The NY Grassland Bird SAFE (FSA CRP CP38E, Tompkins County eligible) regulates mowing after August 15 and grazing intensity, with no landowner bird survey.

### How acoustic evidence fits, and where it does not count

Fits: as the dated field log plus photos that E645D, E645A/B/C and E666R ask for; as the "map showing bird monitoring points" and "reports on bird surveys" for E666R (as a supplement to the required specialist census, not a replacement); as planner-facing supporting information for the "Animals" benchmark condition in CPA-52 section F and the practice narrative in the case file. Each Thicket recording is a timestamped, geolocated field visit record, which is exactly the shape of the log.

Does not count: a Thicket PDF is never the practice certification. WHEG scores are computed by NRCS from habitat structure, not from detections. CART points do not change because of a species list. For NY, confirm which 600-series enhancements are offered in the state list before promising anything.

## 2. New York Agricultural Environmental Management (AEM)

### Who reviews it

The county Soil and Water Conservation District (SWCD) planner (for Ithaca, Tompkins County SWCD), with NYS Department of Agriculture and Markets and the NYS Soil and Water Conservation Committee funding the AEM Base Program and the implementation grants (Climate Resilient Farming, Agricultural Non-Point Source Abatement and Control). Farmers do not submit to the state directly; the District does.

### The five tiers and their paperwork

| Tier | What happens | Documentation that exists |
|---|---|---|
| 1 | Inventory questionnaire | AEM Tier 1 form header: Tier 1 AEM Identification Number, County SWCD, Date, Evaluator Name, Evaluating Agency, Watershed Identification, Farm Name, Owner's Name, Operator's Name, contacts. Acreage table includes "Wildlife Land". Checkbox "Wildlife Habitat Improvement" under Other Agricultural Conservation Interests |
| 2 | Worksheet assessment, each row rated 1 (low concern) to 4 (high) | Core worksheets: Watershed Site Evaluation, Agriculture and the Community, Greenhouse Gas Mitigation Opportunities, Soil Management, Nutrient Management, Manure and Fertilizer Storage, Waste Disposal, Pesticide Use, Pesticide Storage, Farmstead Water Supply, Stream and Floodplain Management, Petroleum Storage, Forest Management, Irrigation Water Management; livestock specialty includes Pasture Management. Header on every worksheet: AEM ID, Date. Output: AEM Tier 2 Summary Report Template with columns Worksheet Name and Number, Level of Concern (1-4), Items of Concern, Evaluation and Recommendations |
| 3 | Conservation plan (3A whole-farm, 3B component) | planner-written plan; implementation grants require projects "developed from an appropriate AEM Tier 3A or 3B plan" |
| 4 | BMP implementation with funding | SW-3 BMP form by NRCS practice code, acres, procurement records, before and after photos, final report within 60 days (CRF RFP) |
| 5 | Evaluation | Tier 5A documents changes in business practices since the last visit; Tier 5B evaluates installed BMPs to confirm they function as intended (Tompkins SWCD AEM Strategic Plan 2020). No state Tier 5 form is published; "Options for work in Tiers 3, 4, and 5 are discussed between farmers and planners" (AEM Planning Resources) |

### Worksheet rows where habitat evidence is relevant

Stream and Floodplain Management: livestock access to the stream (1 "no access" to 4 "full uncontrolled access"); predominant width of streamside vegetation (1 "100 or more ft. on both sides", 4 "less than 35 ft"); bank vegetation condition (1 includes shade over 50% of stream width and overhanging vegetation); indicators of good water quality (1 "A diverse aquatic plant community exists"); fish kills; invasive species along the reach; "How good is the fishing?".

Pasture Management: time on a single pasture, pasture condition (1 "densely vegetated" to 4 "large areas with little vegetation"), laneways, attractant distance from water, stream fencing with a 35 ft buffer, seasonal watercourse management, woodlot access. The worksheet text notes well-managed pasture "enhancing wildlife habitat" but no row scores wildlife directly.

Agriculture and the Community, Natural Resource Protection Benefits: Stream Corridor Management (riparian buffer length), Woodland Management (acres, forest type, plan), Wildlife Management ("game species present", "upland habitat management acreage", "species being managed for", threatened or endangered species habitat), Wetlands, and an "Environmental Impact Monitoring" item on regular inspection of practices.

Watershed Site Evaluation, Part 3: checkboxes for threatened or endangered species, invasive species, regulated wetland.

### NY Climate Resilient Farming and Ag Non-Point Source grants

CRF (Round 9 RFP; Round 10 announced September 2026): Districts apply; tracks are 1 livestock methane, 2 adaptation and resiliency (riparian buffers, stream stabilization, access control), 3 Healthy Soils NY (prescribed grazing, cover crops, agroforestry; "strongly encourages applicants to enhance on-farm biodiversity through utilizing plant species that support pollinator habitat"), 4 agricultural forestry. GHG estimates use COMET-Planner. Closeout: "comprehensive final report ... no later than 60 days following completion", before and after photos, procurement records, expenditure summary, engineer's certification where needed; cover-and-flare and soil health projects "will be required to conduct or participate in some measurement, monitoring, reporting, and verification of GHG reduction". No biodiversity monitoring requirement. AgNPS (RFP 0395): Districts choose planning (Tier 3) or implementation (Tier 4) projects; BMP systems come from the NYS Agricultural BMP Systems Catalogue (Riparian Buffer System, Access Control System incl. 472, 382, 378, 578, Prescribed Rotational Grazing System, Stream Corridor and Shoreline Management System, Forestry/Agroforestry System), each referencing NRCS standards and O&M.

### How acoustic evidence fits, and where it does not count

Fits: a Tier 5B evaluation annex for a riparian buffer, access control or prescribed grazing BMP, giving the planner a dated before/after soundscape comparison next to the worksheet rows above; the "Wildlife Management" and "Environmental Impact Monitoring" items on the Agriculture and the Community worksheet; narrative support in a Tier 3 plan for a farmer who ticked "Wildlife Habitat Improvement". Districts take evidence informally (planner notes, photos, GIS layers; Tompkins keeps "a GIS Database for documenting all AEM Tier IV projects since 2005"), so a short PDF with the AEM ID in the header is what will actually get filed.

Does not count: no worksheet row is scored from species data; CRF and AgNPS score water quality and GHG outcomes, not biodiversity. Nothing in AEM asks for monitoring reports from the farmer.

## 3. Regenerative and bird-friendly certifications

| Program | Reviewer | Biodiversity requirement | Format | Acoustic fit |
|---|---|---|---|---|
| Regenerative Organic Certified (ROC), Framework 2023 | ROA-accredited certifier (e.g. FoodChain ID) during the organic-style audit | Pillar 1 Soil Health and Land Management: criterion 1.2 Regenerative Organic System Plan must include a "Record of native flora and fauna on farm"; 2.4 sensitive areas (habitat for declining and rare species, wetlands, riparian) not grazed at damaging times; 2.6 "identify, monitor, and manage" invasive plants and animals; 2.8 counts practices such as "Pollinator Habitats, Insectary Strips, or Wildlife Habitat" and "Riparian Restoration" (3 practices Bronze, 5+ Gold); soil lab tests every three years, in-field tests every audit | ROSP document plus records; no species survey protocol prescribed | Strong fit as the "Record of native flora and fauna" and as evidence that habitat practices in 2.8 exist and are used by wildlife. Nothing in ROC accepts or rejects acoustics specifically |
| Land to Market / Savory Ecological Outcome Verification (EOV) | Accredited EOV Monitor (STM, can be the farmer for short-term only) and Hub Verifier (LTM, reports, audits); 5% of farms audited yearly | Short-Term Monitoring yearly: 15 indicators on a regional scorecard (live canopy abundance, living organisms, desirable/undesirable species, litter, litter incorporation, dung decomposition, bare soil, soil capping, wind and water erosion, and so on) summed into the Ecological Health Index (EHI), range -100 to +130. Long-Term Monitoring at year 0 and every 5 years: minimum three permanent sites, each with a photo plot and three transects (line-point and flexible area, 100 ft EHI transect with 10 quadrats); bare ground, litter, foliar cover by species, functional groups, "Species Richness and Shannon-Wienner Index" (plants), water infiltration, soil carbon by depth, Haney and Cornell soil health packages | Savory EOV Data Platform (GPS, photos, comments); results report to the producer; Land to Market Verified seal when "EOV data indicates land regeneration" | No fauna, bird or insect monitoring in the protocol. Acoustic data can only be attached as a voluntary annex for the Hub Verifier's narrative or as part of a farm's own evidence; it does not enter the EHI |
| Audubon Conservation Ranching (ACR), protocols Sept 2023 | Audubon staff approve the Habitat Management Plan (protocol 1.45 R(1)); annual third-party verification audit; bird monitoring by Audubon or a partner such as Bird Conservancy of the Rockies | HMP must contain Ecological Site Description and maps (NWI where applicable), "A list of priority bird species and description of general habitat needs", a farm-scale review of habitat available to priority birds, a plan map with pasture IDs, cover types, important bird habitat areas, invasive weeds; management goals with grazing system, timeline, monitoring approach, cost-share references. Records: 1.47 "Pasture condition is evaluated on an ongoing basis", 1.49 herd rotation documentation, herd health, body condition. Rancher signs: "I agree to allow staff of the Bird Conservancy of the Rockies (or other Audubon partner) to enter my property and conduct this required monitoring" | Audubon's Bird-Friendliness Index: IMBCR-style 6 minute unlimited-distance point counts with laser rangefinder distances, points 250 m apart, time-removal and distance sampling to get detection-corrected densities, weighted by Partners in Flight combined conservation scores and a functional diversity term, scaled 0 to 1 (Michel et al. 2020). 2024 Impact Report: BFI up "nearly 63% over the 7-year life of the program"; Audubon "looks to test Acoustic Recording Units as a new tool in bird monitoring" | Landowner-collected data do not feed the BFI. Acoustic output fits the HMP's own "monitoring approach" section, the priority-species habitat review, and the annual audit as evidence that the HMP is being followed. ARUs are being tested by Audubon, so a clean, well-documented package could be welcomed as corroboration, not as the index |
| Regenified 6-3-4 (2024 revision) | Field verifier on site; Verification Review Board | Section 3.10 Community Dynamics: field verifier looks for "evidence of three to five different types of beneficial organisms", "three to five different types of animals", and bird diversity "three to five different types (song, game, raptor) of local and migratory species"; plant diversity must increase between verifications; Haney and PLFA lab trends | Verifier observation plus producer plan, aerial imagery, records | A dated species list with audio clips is direct evidence for the bird and animal items, but the standard says the verifier observes; treat Thicket output as the producer's supporting record |
| A Greener World Certified Regenerative | AGW auditor and expert panel review the Regenerative Plan yearly | Plan must answer "What flora or fauna is present on the holding, including migratory bird/animals species?", protected species, important habitats, and include a "Plan for the protection or improvement of biodiversity" with "Measurable results: ... how will this be assessed and how often? You might consider test results, photos" | Narrative plan; no fixed template for biodiversity | A repeatable acoustic survey is a credible "measurable result" to write into the plan |
| Certified Wildlife Friendly (WFEN) | WFEN with species experts; criteria tailored to local context | "key species of wildlife are protected for net positive impact"; enterprises have "put in place monitoring programs" | Case by case | Only relevant if a focal species can be detected acoustically; no US farm template |

## 4. Biodiversity and carbon credit standards

| Standard | Reviewer | Required monitoring content | Acoustic acceptance |
|---|---|---|---|
| Verra CCB Standards v3.1 (biodiversity section) | Verra-approved validation/verification body (VVB) | B1 baseline incl. High Conservation Values; B2 net positive impacts using appropriate methods; B3 offsite impacts; B4 monitoring: a plan that "includes the biodiversity variables to be monitored, areas, sampling methods and reporting frequency", a plan to assess effectiveness of HCV measures, and the duty to "Publicly communicate the monitoring plan and results, and ensure they are available on the internet". The CCB and VCS Monitoring Report template puts this in 5 Biodiversity: 5.1 Net Positive Biodiversity Impacts, 5.2 Offsite Biodiversity Impacts, 5.3 Biodiversity Impact Monitoring, 5.4 Exceptional Biodiversity Benefits, plus 2 Project Details (implementation status, safeguards, management capacity, legal status) | Method-agnostic. Reviewers judge whether variables, sampling and frequency match the stated biodiversity objectives. Acoustic species richness and target-species presence are routinely used in forest projects; detection counts are not accepted as abundance without a detection model |
| Verra SD VISta Nature Framework v1.0 (Oct 2024, SDVM002) | VVB meeting Nature Framework VVB requirements; verification "at least every five years during the crediting period" | Unit: Nature Credit = 1% of net outcome measured in Quality Hectares (Extent x Condition). Condition from indicators in Composition, Structure, Function and Pressures; Composition and Structure are mandatory with "at least two and three indicators, respectively"; each indicator normalized 0 to 1 against a reference (mature long-undisturbed or "Best on Offer") and averaged. Significance is reported separately and does not change issuance. Social safeguards (FPIC, benefit sharing) | Composition indicators are where species data enter. Acoustically derived bird species richness or occupancy can be a composition indicator if sampled "regularly" and "standardized"; Verra's own text does not name acoustics. Worked examples PDF exists but is behind robots rules; read it before designing indicators |
| Plan Vivo PV Nature, Methodology and Data Protocol v1.2 (2026) and Procedures v1.1 | Plan Vivo Foundation, approved third-party data analytics providers, VVB or Independent Expert | Five Pillar Metrics: 1 Species Richness (Hill q=0), 2 Species Diversity (Hill q=1), 3 Taxonomic Dissimilarity, 4 Habitat Health (NDVI based), 5 Habitat Spatial Structure (connectivity, every 5 years). Terrestrial projects need at least four target groups; plants under 2 m and birds are mandatory; add two from mammals, bats, an invertebrate group, amphibians, reptiles, trees, lichens and mosses, soil eDNA. Sampling about 1 location per 10 ha, random stratified by habitat, 100 m minimum spacing, re-randomized yearly, at least once per year at a consistent season, species accumulation curves must begin to plateau. "All data must be digitally recorded" with location, date, time and "Unique sensor/hardware ID"; "an auditable data trail" from record to analysis. Species IDs "derived by an approved third-party data analytics provider from the digital data"; data must allow "calculation of species detection probability and classification error"; "Active searching" rejected for observer bias. Issuance: restoration certificate = 1% increase in the multimetric per hectare per year, only changes outside 95% CIs count in years 2 to 5, hierarchical model from year 5; conservation certificates only for KBA/IPA sites | Closest match to Thicket. Digital, timestamped, sensor-tagged bird audio with classifier confidences is exactly what the Data Protocol wants, but the species identification step belongs to the approved analytics provider, so Thicket's role is data capture, QC and provenance, not the certified identification |
| Wallacea Trust biodiversity credit methodology (v3, 2022) | Verifier and registry (buffer pool) | Credit: "A 1% uplift in biodiversity per hectare, as measured by the median % change in a basket of biodiversity metrics". At least five site-specific, peer-reviewed metrics (typically one structural such as canopy cover and four taxon metrics such as breeding birds or butterflies); non-structural metric = sum of relative abundance scores x conservation value scores; baseline on project and reference site, remeasured every five years at the same sampling locations | Bird and bat metrics in Wallacea baskets are commonly surveyed acoustically in practice; the methodology text does not restrict the survey method but does require consistent, repeatable sampling |
| TNFD (recommendations 2023, LEAP guidance v1.1, state-of-nature discussion paper 2026) | Corporate disclosure, no verifier; assurance providers if the reporter chooses | Core global metrics C1.0 to C7.4 (spatial footprint, land use change, pollution, water, high-risk commodities, invasive species measures, risk and opportunity values). C5.0 Ecosystem condition and C5.1 Species extinction risk are placeholders: "The TNFD does not currently specify one metric as no single metric will capture all relevant dimensions". State of nature is framed as ecosystem extent, ecosystem condition (composition, structure, function), species extinction risk and species population size; example tools are Mean Species Abundance, STAR, Forest Landscape Integrity Index | A farm would appear in a buyer's LEAP Evaluate step as a site-level composition indicator. Acoustic richness is usable as supporting primary data; TNFD does not prescribe field methods |

Common reviewer expectations across the credit standards for a monitoring report: project and proponent identity, boundary polygon and strata map, monitoring period, baseline description and date, indicator definitions, sampling design (sites, spacing, effort, season, repeats), equipment and settings, identification method and version, validation and error rates, QA/QC steps, uncertainty (confidence intervals or model), data provenance (file hashes, who collected and processed), deviations from the plan, raw data availability, public summary.

## 5. Cross-cutting: how credible acoustic monitoring is reported

Metadata that every serious acoustic report carries, with the standard that demands it:

| Field | Required by |
|---|---|
| Surveyor and analyst names, qualifications | USFWS range-wide bat survey guidelines 2026 ("Surveys lacking this information will not be reviewed") |
| Detector and microphone make, model, settings, weatherproofing, orientation, height | USFWS 2026; NABat stationary point form (Bat detector manufacturer, model, Microphone type, Microphone height (m), Recording mode, Gains, Frequency Band Filters, Calibration method); GUANO (Make, Model, Serial, Firmware Version) |
| Site map with aerial imagery and a table of GPS coordinates per detector; photos of each detector with scale | USFWS 2026 |
| Dates, start and stop times, nightly or daily effort, survey hours | USFWS 2026; NABat; Darwin Core samplingEffort |
| Weather per night (temperature, precipitation, wind), with validity rules | USFWS 2026 (invalid if below 10 C in first 5 hours, rain over 30 min, wind over 4 m/s for 30 min); NABat high/low temp, RH, wind per night |
| Software name, version and settings used for automated ID; approved vs candidate status | USFWS 2026 ("Name of Service-approved and/or Candidate software program(s) used, including version(s) and software settings"); NABat Kaleidoscope guidance |
| Output per site per night: number of files, species composition, manual vetting table with rationale for changes | USFWS 2026; NABat ("minimum of one audio file per species per night" for presence) |
| Raw audio retained and producible: five years for USFWS | USFWS 2026 |
| Recording timestamp (ISO 8601), position, accuracy, elevation, sample rate, length, Species Auto ID vs Species Manual ID | GUANO specification |
| Occurrence record vocabulary: occurrenceID, basisOfRecord = MachineObservation, eventID, eventDate, samplingProtocol, samplingEffort, decimalLatitude/Longitude, geodeticDatum, coordinateUncertaintyInMeters, scientificName, identifiedBy (model and version), dateIdentified, identificationVerificationStatus, identificationRemarks (score), occurrenceStatus, associatedMedia, dynamicProperties (JSON for confidence) | Darwin Core; the 2025 Gothenburg BirdNET dataset published this way with identifiedBy "BirdNET [v1.3.1]", threshold 0.85, and 50 expert-reviewed files per species |
| Media metadata: ac:captureDevice, ac:resourceCreationTechnique, ac:mediaDuration, mo:sample_rate, ac:hashFunction/ac:hashValue, dcterms:rights, xmpRights:UsageTerms | Audiovisual (Audubon) Core; UK ecoacoustic good practice guidelines recommend aligning metadata to Audubon Core |
| Classifier score handling: species-specific thresholds, validation sample, precision at threshold, model version; scores "are not probabilities" | Wood and Kahl 2024 guidelines for BirdNET scores |
| Deployment design: 48 kHz, 16 bit or more, about +20 dB gain, WAV or FLAC, 1 min every 5 min around the clock, one week per season, recorders 250 m apart, 1 to 2 m high, parallel human surveys to check | UK good practice guidelines for long-term ecoacoustic monitoring (Metcalf et al. 2023) |
| Agri-environment payment context: presence of target species, richness of birds or bats, vocal activity are the usable indicators; "standardised protocols are currently lacking"; recordings serve as "objective, observer-independent evidence" | Leveraging PAM for result-based agri-environmental schemes (Biological Conservation 2025) |

US programs comparable to UK Biodiversity Net Gain: none at state level. The US has habitat exchanges and conservation banks (Colorado Habitat Exchange, Central Valley Habitat Exchange, Nevada Conservation Credit System) built on Habitat Quantification Tools catalogued by USGS (database v2.0, 2022); they score habitat condition for species mitigation and are not a reporting target for a NY farm.

BirdNET-Analyzer parameters that must be printed on any report using BirdNET output: model version (GLOBAL 6K v2.4), min_conf, sensitivity, overlap, lat, lon, week, sf_thresh (location filter threshold), fmin/fmax, merge behaviour. Thicket already stores the equivalents (raw_threshold, decision_threshold, hop_seconds, merge_gap_seconds, location_filter, location_filter_threshold, model_sha256).

## 6. Thicket report templates

Design rules for all five: every number on a page comes from one Analysis at one decision_threshold; every page footer prints analysis_id, software_version, schema_version and the SHA-256 of the exported JSON; every species table carries the plausibility and review columns; abundance language is banned (see section 8). Thicket cannot sign anything; signature blocks are for the people named on the form.

### (a) Thicket Evidence Package (generic, most rigorous)

| Page | Content | Thicket fields | User-entered fields |
|---|---|---|---|
| 1 Cover | title, property, period, prepared by, prepared for, analysis_id list, export checksum | analysis.id, created_at, completed_at, software_version | organization_name, preparer_name, preparer_role, prepared_for, property_name, report_title |
| 2 Summary | what was recorded, where, when; headline table: recordings, total minutes, species counted, richness, Shannon, QC status; one paragraph of limits | recording.*, metrics.*, quality.status, warnings | monitoring_objective |
| 3 Site and deployment | map with recorder points on parcel outline; deployment table | recording.latitude, longitude, site_name, captured_at, timezone, recorder_type | recorder_make, recorder_model, recorder_serial, firmware_version, microphone_type, mount_height_m, orientation, gain_setting, recording_schedule, deployment_start, deployment_end, gps_accuracy_m, habitat_type, land_use, distance_to_edge_m, deployment_photo, deployed_by, weather_summary |
| 4 Methods | pipeline diagram; model card excerpts; thresholds; consolidation; plausibility rule; QC head; indices definitions | settings.*, model_runs.*, model cards | survey_protocol_reference (if any) |
| 5 Results: species | species table (common, scientific, taxon, events, first/last, max/mean confidence, plausibility, review) | species[] | none |
| 6 Results: timeline and metrics | event timeline per recording; metrics table; acoustic indices table with the note that indices are not species counts | events[], metrics, acoustic_indices | none |
| 7 Quality | QC report, clipping, silence, speech flag, soundscape QC categories | quality.* | none |
| 8 Review log | each reviewed event: id, model label, reviewer label, status, note; validation summary (n reviewed, n accepted) | events[].review_status, reviewed_label, review_note | reviewer_name, reviewer_qualifications, review_date, validation_method |
| 9 Limitations | fixed text plus analysis warnings: no abundance, no recall estimate, range filter only for birds, QC head field caveat, frog/insect head status | warnings, model card limits | caveats_acknowledged |
| 10 Provenance appendix | file hashes, byte sizes, durations, model_sha256, configuration JSON, settings JSON, stage timings, export filenames and checksums, retention statement | recording.checksum_sha256, model_runs.model_sha256, configuration, settings, stage_timings_ms | audio_retention_statement, data_license, privacy_statement |
| 11 Data dictionary and attestation | CSV column list with definitions; attestation lines | CSV_COLUMNS | attestation_name, attestation_date |

### (b) NRCS practice documentation annex

Purpose: slot into the case file as the "field log", "photos" and "map" that enhancement sheets ask for, and as supporting information for the planner. Four to six pages.

| Page | Content | Thicket fields | User-entered fields |
|---|---|---|---|
| 1 Header | NRCS-style identifier block | none | participant_name (as on contract), nrcs_program, nrcs_contract_number, fsa_farm_number, fsa_tract_number, fsa_field_numbers, county, state, practice_code, practice_name, enhancement_code, contract_item_number, planned_amount, applied_amount, amount_unit, fiscal_year, nrcs_planner_name, conservation_plan_id |
| 2 Field log | one row per recording: date, time, field number, site, duration, who deployed, weather, "monitoring activity performed" | recording.captured_at, timezone, site_name, duration_seconds | site_field_map, deployed_by, weather_summary, management_action_dates |
| 3 Map and photos | recorder points on the FSA tract map; deployment photos | latitude, longitude | tract_map_image, deployment_photo |
| 4 Target species presence | for each target species in the plan: detected or not detected per date, max confidence, plausibility, review status; "not detected" is stated as "not detected in this effort" | species[], events[] | target_species, habitat_objectives |
| 5 Habitat context | one paragraph on structure and limiting factors the planner wrote, with Thicket's QC and indices as context only | acoustic_indices, quality | limiting_factors, habitat_management_plan_reference |
| 6 Provenance and statement | checksums, model version, threshold; fixed statement: "Supporting documentation prepared by the participant. Not a practice certification, WHEG score or CART assessment." | provenance set | attestation_name, attestation_date |

### (c) NY AEM Tier 5 evaluation annex

| Page | Content | Thicket fields | User-entered fields |
|---|---|---|---|
| 1 Header | AEM ID, County SWCD, Date, Evaluator Name, Evaluating Agency, Farm Name, Owner, Operator, Watershed, Tier (5A or 5B) | none | aem_id, county_swcd, swcd_planner_name, evaluating_agency, farm_name, owner_name, operator_name, watershed_name, huc12, aem_tier |
| 2 BMP under evaluation | BMP system from the NYS catalogue, NRCS practice codes, install date, funding source, project number | none | bmp_system, practice_code, bmp_install_date, funding_program, project_contract_number |
| 3 Worksheet linkage | the Tier 2 worksheet rows this evidence speaks to (Stream and Floodplain 6, 8, 9, 12, 17; Pasture 3, 8, 10; Ag and Community Wildlife Management) with level of concern before and after | none | tier2_worksheets_completed, worksheet_rows_addressed, level_of_concern_before, level_of_concern_after |
| 4 Before and after | season-matched comparison: species counted, richness, indices, per site; explicit note on effort differences | species[], metrics, acoustic_indices per analysis | baseline_analysis_ids, follow_up_analysis_ids |
| 5 Field evidence | recorder map, photos, recording log | latitude, longitude, captured_at | deployment_photo, deployed_by |
| 6 Planner notes and provenance | free text, checksums, statement that the SWCD planner owns the evaluation | provenance set | planner_notes, attestation_name, attestation_date |

### (d) Certification monitoring summary (ROC, Land to Market EOV, Audubon ACR, Regenified, AGW)

| Page | Content | Thicket fields | User-entered fields |
|---|---|---|---|
| 1 Header | program, certifier or verifier, certification ID, audit date, operation name, land base acres | none | certification_program, certifier_name, certification_id, audit_date, operation_name, land_base_acres |
| 2 Management context | grazing or cropping system, paddock or pasture IDs covered, habitat practices in place (ROC 2.8 list), HMP reference (ACR) | none | pasture_or_paddock_ids, grazing_system_description, habitat_practices, hmp_reference, management_changes_since_last_period |
| 3 Native fauna record | species list by taxon with dates, confidence, plausibility, review; priority species flagged (ACR) | species[], events[] | priority_species, sensitive_areas |
| 4 Monitoring design | sites (mapped to EOV LTM sites if any), schedule, recorder metadata | recording.* | eov_site_ids, recorder_make, recorder_model, mount_height_m, recording_schedule |
| 5 Indicators and trend | richness, Shannon, indices per period; trend only when effort and season match | metrics, acoustic_indices | baseline_analysis_ids, follow_up_analysis_ids |
| 6 Limits and provenance | what this is not (not the BFI, not the EHI, not a verifier observation); checksums | provenance set | attestation_name, attestation_date |

### (e) Biodiversity credit monitoring report (CCB, PV Nature, Nature Framework, TNFD-aligned)

| Page | Content | Thicket fields | User-entered fields |
|---|---|---|---|
| 1 Project details | project ID and registry, proponent, standard and version, monitoring period, boundary and strata map, land tenure note | none | project_id, registry, standard_version, project_proponent, monitoring_period_start, monitoring_period_end, project_boundary_file, strata_definitions, vvb_name, land_tenure_note |
| 2 Monitoring plan vs implemented | indicators, sampling design (sites per stratum, spacing, effort, season, repeats), deviations | recording counts per site | indicator_set, sampling_design_description, deviations_from_plan, reference_site_ids |
| 3 Equipment and data capture | recorder table per deployment with serials, firmware, settings, schedule, GPS accuracy; chain of custody from device to upload | recording.checksum_sha256, byte_size, captured_at, recorder_type | recorder_make, recorder_model, recorder_serial, firmware_version, gain_setting, sample_rate_setting, recording_schedule, mount_height_m, chain_of_custody_notes |
| 4 Identification method | model, version, hash, thresholds, consolidation, plausibility, QC head; validation design and results (n reviewed per species, precision at threshold) | model_runs.*, settings.*, review fields | validation_method, reviewer_name, reviewer_qualifications, analytics_provider (PV Nature) |
| 5 Results | per stratum and period: species richness (Hill q=0), Shannon (Hill q=1 as exp(H') where asked), evenness, Simpson, indices; species accumulation across recordings | metrics, species[], acoustic_indices | none |
| 6 Baseline comparison and uncertainty | change vs baseline with confidence intervals from resampling across recordings; statement when effort differs; no credit arithmetic | per-analysis metrics | baseline_period_reference, uncertainty_method |
| 7 QA/QC | QC pass rates, excluded recordings and why, speech and privacy handling, duplicate and clock checks | quality.*, warnings | qaqc_notes |
| 8 Data provenance and availability | file manifest with hashes, Darwin Core occurrence export description, raw audio retention, access conditions, licence | CSV/JSON exports, checksums | audio_retention_statement, data_license, data_access_conditions |
| 9 Safeguards and public summary | consent for recording on the land, privacy, one-page public summary text | speech_detected | landowner_consent, privacy_statement, public_summary_text |
| 10 Attestation | preparer and reviewer sign-off | none | attestation_name, attestation_date |

Build order recommendation: (a) first, because (b) to (e) are subsets of (a) with different headers; (c) next for the Ithaca pilot (the SWCD is the nearest reviewer); (e) last, after sites, deployments and multi-recording trends exist, since a credit reviewer will reject a report built from single ten-minute clips.

## 7. `report_field_schema`

Every field the user must enter because Thicket cannot know it. `templates` uses a to e from section 6. Types: string, text, date, datetime, number, integer, boolean, enum, list, file.

```json
{
  "report_field_schema": {
    "version": "0.1",
    "groups": ["identity", "location", "deployment", "review", "nrcs", "aem", "certification", "credit", "statements"],
    "fields": [
      {"name": "report_title", "type": "string", "group": "identity", "templates": ["a","b","c","d","e"], "example": "Spring 2027 acoustic survey, north pasture"},
      {"name": "organization_name", "type": "string", "group": "identity", "templates": ["a","b","c","d","e"], "example": "Fall Creek Grazing LLC"},
      {"name": "preparer_name", "type": "string", "group": "identity", "templates": ["a","b","c","d","e"], "example": "Shourya Mehta"},
      {"name": "preparer_role", "type": "string", "group": "identity", "templates": ["a","b","c","d","e"], "example": "Farm manager"},
      {"name": "prepared_for", "type": "string", "group": "identity", "templates": ["a","d","e"], "example": "Tompkins County SWCD"},
      {"name": "property_name", "type": "string", "group": "location", "templates": ["a","b","c","d","e"], "example": "Hilltop Farm"},
      {"name": "property_address", "type": "string", "group": "location", "templates": ["a","b","c","d"], "example": "123 Ellis Hollow Rd, Ithaca, NY 14850"},
      {"name": "county", "type": "string", "group": "location", "templates": ["a","b","c"], "example": "Tompkins"},
      {"name": "state", "type": "string", "group": "location", "templates": ["a","b","c"], "example": "NY"},
      {"name": "monitoring_objective", "type": "text", "group": "identity", "templates": ["a","d","e"], "example": "Document grassland bird use of the rotationally grazed north pasture"},
      {"name": "habitat_type", "type": "enum", "group": "location", "options": ["pasture","hayfield","cropland","shrubland","forest","wetland","riparian buffer","farmstead","other"], "templates": ["a","b","c","d","e"], "example": "pasture"},
      {"name": "land_use", "type": "string", "group": "location", "templates": ["a","b","c","d"], "example": "Rotational grazing, 12 paddocks"},
      {"name": "site_field_map", "type": "list", "group": "location", "item": {"site_name": "string", "fsa_field_number": "string", "paddock_id": "string"}, "templates": ["b","c","d"], "example": [{"site_name": "North pasture", "fsa_field_number": "4", "paddock_id": "P4"}]},
      {"name": "recorder_make", "type": "string", "group": "deployment", "templates": ["a","b","c","d","e"], "example": "Open Acoustic Devices"},
      {"name": "recorder_model", "type": "string", "group": "deployment", "templates": ["a","b","c","d","e"], "example": "AudioMoth 1.2.0"},
      {"name": "recorder_serial", "type": "string", "group": "deployment", "templates": ["a","e"], "example": "24A1F3C9"},
      {"name": "firmware_version", "type": "string", "group": "deployment", "templates": ["a","e"], "example": "1.11.0"},
      {"name": "microphone_type", "type": "string", "group": "deployment", "templates": ["a","e"], "example": "Built-in MEMS"},
      {"name": "mount_height_m", "type": "number", "group": "deployment", "templates": ["a","c","d","e"], "example": 1.5},
      {"name": "orientation", "type": "string", "group": "deployment", "templates": ["a","e"], "example": "Facing south, open aspect"},
      {"name": "gain_setting", "type": "string", "group": "deployment", "templates": ["a","e"], "example": "Medium"},
      {"name": "sample_rate_setting", "type": "integer", "group": "deployment", "templates": ["a","e"], "example": 48000},
      {"name": "recording_schedule", "type": "string", "group": "deployment", "templates": ["a","c","d","e"], "example": "1 min every 5 min, 04:30 to 09:30 and 19:00 to 22:00"},
      {"name": "deployment_start", "type": "datetime", "group": "deployment", "templates": ["a","b","c","d","e"], "example": "2027-05-10T18:00:00-04:00"},
      {"name": "deployment_end", "type": "datetime", "group": "deployment", "templates": ["a","b","c","d","e"], "example": "2027-05-17T09:00:00-04:00"},
      {"name": "gps_accuracy_m", "type": "number", "group": "deployment", "templates": ["a","e"], "example": 4},
      {"name": "distance_to_edge_m", "type": "number", "group": "deployment", "templates": ["a","e"], "example": 60},
      {"name": "deployment_photo", "type": "file", "group": "deployment", "templates": ["a","b","c","e"], "example": "north_pasture_recorder.jpg"},
      {"name": "deployed_by", "type": "string", "group": "deployment", "templates": ["a","b","c","e"], "example": "S. Mehta"},
      {"name": "weather_summary", "type": "text", "group": "deployment", "templates": ["a","b","e"], "example": "Clear, 8 to 14 C, wind under 3 m/s on survey mornings"},
      {"name": "survey_protocol_reference", "type": "string", "group": "deployment", "templates": ["a","e"], "example": "UK ecoacoustic good practice quick-start, adapted"},
      {"name": "reviewer_name", "type": "string", "group": "review", "templates": ["a","d","e"], "example": "J. Doe"},
      {"name": "reviewer_qualifications", "type": "text", "group": "review", "templates": ["a","e"], "example": "10 years NY breeding bird atlas volunteer; eBird reviewer"},
      {"name": "review_date", "type": "date", "group": "review", "templates": ["a","d","e"], "example": "2027-05-20"},
      {"name": "validation_method", "type": "text", "group": "review", "templates": ["a","e"], "example": "All events above 0.60 listened to; 20 random events per species below 0.60"},
      {"name": "analytics_provider", "type": "string", "group": "review", "templates": ["e"], "example": "Approved PV Nature data analytics provider name"},
      {"name": "participant_name", "type": "string", "group": "nrcs", "templates": ["b"], "example": "Jane Farmer"},
      {"name": "nrcs_program", "type": "enum", "group": "nrcs", "options": ["EQIP","CSP","RCPP","other"], "templates": ["b"], "example": "CSP"},
      {"name": "nrcs_contract_number", "type": "string", "group": "nrcs", "templates": ["b"], "example": "74-2B29-26-123"},
      {"name": "fsa_farm_number", "type": "string", "group": "nrcs", "templates": ["b","c"], "example": "1234"},
      {"name": "fsa_tract_number", "type": "string", "group": "nrcs", "templates": ["b","c"], "example": "5678"},
      {"name": "fsa_field_numbers", "type": "list", "group": "nrcs", "item": "string", "templates": ["b","c"], "example": ["3","4"]},
      {"name": "practice_code", "type": "string", "group": "nrcs", "templates": ["b","c"], "example": "645"},
      {"name": "practice_name", "type": "string", "group": "nrcs", "templates": ["b","c"], "example": "Upland Wildlife Habitat Management"},
      {"name": "enhancement_code", "type": "string", "group": "nrcs", "templates": ["b"], "example": "E645D"},
      {"name": "contract_item_number", "type": "string", "group": "nrcs", "templates": ["b"], "example": "3"},
      {"name": "planned_amount", "type": "number", "group": "nrcs", "templates": ["b"], "example": 42.0},
      {"name": "applied_amount", "type": "number", "group": "nrcs", "templates": ["b"], "example": 42.0},
      {"name": "amount_unit", "type": "enum", "group": "nrcs", "options": ["ac","ft","no","ea"], "templates": ["b"], "example": "ac"},
      {"name": "fiscal_year", "type": "integer", "group": "nrcs", "templates": ["b"], "example": 2027},
      {"name": "nrcs_planner_name", "type": "string", "group": "nrcs", "templates": ["b"], "example": "District Conservationist name"},
      {"name": "conservation_plan_id", "type": "string", "group": "nrcs", "templates": ["b"], "example": "NY-TOMP-00123"},
      {"name": "target_species", "type": "list", "group": "nrcs", "item": "string", "templates": ["b","d"], "example": ["Bobolink","Eastern Meadowlark","Savannah Sparrow"]},
      {"name": "habitat_objectives", "type": "text", "group": "nrcs", "templates": ["b"], "example": "Maintain 8 to 12 inch residual cover through July 15"},
      {"name": "limiting_factors", "type": "text", "group": "nrcs", "templates": ["b"], "example": "Early hay cutting; lack of residual cover"},
      {"name": "habitat_management_plan_reference", "type": "string", "group": "nrcs", "templates": ["b","d"], "example": "WHMP dated 2026-11-02"},
      {"name": "management_action_dates", "type": "list", "group": "nrcs", "item": {"action": "string", "date": "date"}, "templates": ["b","c","d"], "example": [{"action": "Delayed first cut", "date": "2027-07-20"}]},
      {"name": "tract_map_image", "type": "file", "group": "nrcs", "templates": ["b"], "example": "fsa_tract_5678.png"},
      {"name": "aem_id", "type": "string", "group": "aem", "templates": ["c"], "example": "T-0456"},
      {"name": "county_swcd", "type": "string", "group": "aem", "templates": ["c"], "example": "Tompkins County SWCD"},
      {"name": "swcd_planner_name", "type": "string", "group": "aem", "templates": ["c"], "example": "Planner name"},
      {"name": "evaluating_agency", "type": "string", "group": "aem", "templates": ["c"], "example": "Tompkins County SWCD"},
      {"name": "farm_name", "type": "string", "group": "aem", "templates": ["c"], "example": "Hilltop Farm"},
      {"name": "owner_name", "type": "string", "group": "aem", "templates": ["c"], "example": "Jane Farmer"},
      {"name": "operator_name", "type": "string", "group": "aem", "templates": ["c"], "example": "Jane Farmer"},
      {"name": "watershed_name", "type": "string", "group": "aem", "templates": ["c"], "example": "Fall Creek"},
      {"name": "huc12", "type": "string", "group": "aem", "templates": ["c","e"], "example": "041402010304"},
      {"name": "aem_tier", "type": "enum", "group": "aem", "options": ["5A","5B"], "templates": ["c"], "example": "5B"},
      {"name": "bmp_system", "type": "enum", "group": "aem", "options": ["Riparian Buffer System","Access Control System","Prescribed Rotational Grazing System","Stream Corridor and Shoreline Management System","Forestry / Agroforestry System","Soil Health System","other"], "templates": ["c"], "example": "Access Control System"},
      {"name": "bmp_install_date", "type": "date", "group": "aem", "templates": ["c"], "example": "2025-09-30"},
      {"name": "funding_program", "type": "enum", "group": "aem", "options": ["AgNPS","CRF","EQIP","CSP","self-funded","other"], "templates": ["c"], "example": "AgNPS"},
      {"name": "project_contract_number", "type": "string", "group": "aem", "templates": ["c"], "example": "C00xxxx"},
      {"name": "tier2_worksheets_completed", "type": "list", "group": "aem", "item": "string", "templates": ["c"], "example": ["Pasture Management","Stream and Floodplain Management"]},
      {"name": "worksheet_rows_addressed", "type": "list", "group": "aem", "item": "string", "templates": ["c"], "example": ["Stream and Floodplain 6 livestock access","Stream and Floodplain 8 streamside vegetation width"]},
      {"name": "level_of_concern_before", "type": "integer", "group": "aem", "min": 1, "max": 4, "templates": ["c"], "example": 4},
      {"name": "level_of_concern_after", "type": "integer", "group": "aem", "min": 1, "max": 4, "templates": ["c"], "example": 1},
      {"name": "planner_notes", "type": "text", "group": "aem", "templates": ["c"], "example": "Buffer vegetation established; fence intact"},
      {"name": "certification_program", "type": "enum", "group": "certification", "options": ["ROC","Land to Market EOV","Audubon Conservation Ranching","Regenified","A Greener World Certified Regenerative","Certified Wildlife Friendly","other"], "templates": ["d"], "example": "Audubon Conservation Ranching"},
      {"name": "certifier_name", "type": "string", "group": "certification", "templates": ["d"], "example": "FoodChain ID"},
      {"name": "certification_id", "type": "string", "group": "certification", "templates": ["d"], "example": "ROC-2027-0001"},
      {"name": "audit_date", "type": "date", "group": "certification", "templates": ["d"], "example": "2027-08-15"},
      {"name": "operation_name", "type": "string", "group": "certification", "templates": ["d"], "example": "Hilltop Farm"},
      {"name": "land_base_acres", "type": "number", "group": "certification", "templates": ["d"], "example": 180},
      {"name": "pasture_or_paddock_ids", "type": "list", "group": "certification", "item": "string", "templates": ["d"], "example": ["P1","P2","P3"]},
      {"name": "grazing_system_description", "type": "text", "group": "certification", "templates": ["d"], "example": "Adaptive multi-paddock, 1 to 3 day moves, 35 day rest"},
      {"name": "habitat_practices", "type": "list", "group": "certification", "item": "string", "templates": ["d"], "example": ["Riparian Restoration","Wildlife Habitat"]},
      {"name": "hmp_reference", "type": "string", "group": "certification", "templates": ["d"], "example": "ACR HMP approved 2026-10-01"},
      {"name": "priority_species", "type": "list", "group": "certification", "item": "string", "templates": ["d"], "example": ["Bobolink","Grasshopper Sparrow"]},
      {"name": "sensitive_areas", "type": "text", "group": "certification", "templates": ["d"], "example": "Wet meadow in P7 excluded May to July"},
      {"name": "eov_site_ids", "type": "list", "group": "certification", "item": "string", "templates": ["d"], "example": ["LTM-1","LTM-2"]},
      {"name": "management_changes_since_last_period", "type": "text", "group": "certification", "templates": ["c","d"], "example": "Added 2 paddocks; first cut moved to after Aug 1"},
      {"name": "project_id", "type": "string", "group": "credit", "templates": ["e"], "example": "PV-N-0042"},
      {"name": "registry", "type": "enum", "group": "credit", "options": ["Verra","Plan Vivo","Wallacea Trust aligned","internal","other"], "templates": ["e"], "example": "Plan Vivo"},
      {"name": "standard_version", "type": "string", "group": "credit", "templates": ["e"], "example": "PV Nature Methodology and Data Protocol v1.2"},
      {"name": "project_proponent", "type": "string", "group": "credit", "templates": ["e"], "example": "Hilltop Farm LLC"},
      {"name": "monitoring_period_start", "type": "date", "group": "credit", "templates": ["c","d","e"], "example": "2027-04-01"},
      {"name": "monitoring_period_end", "type": "date", "group": "credit", "templates": ["c","d","e"], "example": "2027-07-31"},
      {"name": "project_boundary_file", "type": "file", "group": "credit", "templates": ["e"], "example": "boundary.geojson"},
      {"name": "strata_definitions", "type": "list", "group": "credit", "item": {"stratum": "string", "habitat_type": "string", "hectares": "number"}, "templates": ["e"], "example": [{"stratum": "S1", "habitat_type": "pasture", "hectares": 40}]},
      {"name": "vvb_name", "type": "string", "group": "credit", "templates": ["e"], "example": "VVB name"},
      {"name": "land_tenure_note", "type": "text", "group": "credit", "templates": ["e"], "example": "Owned in fee; no easement"},
      {"name": "indicator_set", "type": "list", "group": "credit", "item": "string", "templates": ["e"], "example": ["bird species richness (Hill q=0)","bird species diversity (Hill q=1)","ACI"]},
      {"name": "sampling_design_description", "type": "text", "group": "credit", "templates": ["e"], "example": "1 point per 10 ha, stratified by habitat, 100 m spacing, 7 nights per season"},
      {"name": "reference_site_ids", "type": "list", "group": "credit", "item": "string", "templates": ["e"], "example": ["REF-1"]},
      {"name": "deviations_from_plan", "type": "text", "group": "credit", "templates": ["e"], "example": "Recorder at S1-3 failed night 4; redeployed night 5"},
      {"name": "chain_of_custody_notes", "type": "text", "group": "credit", "templates": ["a","e"], "example": "SD cards collected by S. Mehta, uploaded same day, hashes recorded"},
      {"name": "baseline_period_reference", "type": "string", "group": "credit", "templates": ["c","d","e"], "example": "Spring 2026 analyses a1..a9"},
      {"name": "baseline_analysis_ids", "type": "list", "group": "credit", "item": "string", "templates": ["c","d","e"], "example": ["an_01HX..."]},
      {"name": "follow_up_analysis_ids", "type": "list", "group": "credit", "item": "string", "templates": ["c","d","e"], "example": ["an_01HY..."]},
      {"name": "uncertainty_method", "type": "text", "group": "credit", "templates": ["e"], "example": "Bootstrap over recordings, 95% CI"},
      {"name": "qaqc_notes", "type": "text", "group": "credit", "templates": ["e"], "example": "3 recordings excluded for rain per QC head"},
      {"name": "data_access_conditions", "type": "text", "group": "credit", "templates": ["e"], "example": "Raw audio available to the VVB on request for 5 years"},
      {"name": "public_summary_text", "type": "text", "group": "credit", "templates": ["e"], "example": "One paragraph for the public registry page"},
      {"name": "audio_retention_statement", "type": "text", "group": "statements", "templates": ["a","b","e"], "example": "Raw WAV retained offline for 5 years; Thicket RETAIN_AUDIO=false"},
      {"name": "data_license", "type": "enum", "group": "statements", "options": ["CC BY 4.0","CC BY-NC 4.0","CC0","all rights reserved"], "templates": ["a","e"], "example": "CC BY 4.0"},
      {"name": "privacy_statement", "type": "text", "group": "statements", "templates": ["a","e"], "example": "Recordings with detected speech were excluded from export"},
      {"name": "landowner_consent", "type": "boolean", "group": "statements", "templates": ["a","e"], "example": true},
      {"name": "caveats_acknowledged", "type": "boolean", "group": "statements", "templates": ["a","b","c","d","e"], "example": true},
      {"name": "attestation_name", "type": "string", "group": "statements", "templates": ["a","b","c","d","e"], "example": "Jane Farmer"},
      {"name": "attestation_date", "type": "date", "group": "statements", "templates": ["a","b","c","d","e"], "example": "2027-08-01"}
    ]
  }
}
```

## 8. Claims Thicket must not make

| Never write | Why | Write instead |
|---|---|---|
| "X individuals", "population of", "abundance increased", "density" | Events are detections, not animals (spec principle 2; Wood and Kahl 2024; PAM agri-environment review) | "N detection events of species X"; "species X detected on 5 of 7 mornings" |
| "Species X absent" | No recall estimate; detection probability unknown | "Not detected in this effort (N minutes, threshold T)" |
| "Practice certified", "meets NRCS standard", "WHEG score", "CART points" | Only NRCS or a TSP certifies; WHEG and CART are NRCS tools | "Supporting documentation for the participant's field log" |
| "AEM Tier 5 evaluation complete", "level of concern reduced to 1" | The SWCD planner owns the worksheet rating | "Evidence offered for the planner's Tier 5B evaluation" |
| "Bird-Friendliness Index", "EHI", "Regenerating", "verified" | Trademarked or protocol-owned outputs of Audubon and Savory | "Species list and metrics for the certifier's review" |
| "Biodiversity credits earned", "1% uplift", "Quality Hectares" | Issuance belongs to the registry after VVB verification; PV Nature IDs come from the approved analytics provider | "Indicator values for the monitoring period, with intervals" |
| "Compliance with ESA / MBTA / Clean Water Act", "no take" | Regulatory determinations are agency findings (CPA-52 sections G, J, P to S) | Nothing; omit regulatory language |
| "Habitat improved because of the practice" | Causation needs design, controls and time (spec section 1) | "Change between periods, same sites and season, effort noted" |
| "Precision 0.9 in the field" or any accuracy figure | No site gold set yet (docs/VALIDATION.md) | Report the review counts; cite model card limits |
| Frog, insect or mammal species from BirdNET labels as validated | Benchmarked weak (16/40 frogs, 6/80 insects on ESC-50) | Show as "unverified non-bird label" or drop |
| Acoustic indices as "biodiversity score" | Indices respond to weather, noise and insects; UK guidance limits them to well-understood use | "Soundscape index values, context only" |
