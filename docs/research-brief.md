# Data, competitors, and survival

NestCheck's opportunity is real but narrow. The incumbents — Zillow, Redfin, Realtor.com — are actively retreating from honest neighborhood evaluation. Trulia killed its crime maps in 2022. Zillow removed demographic data. Redfin publicly refused to add crime information. This retreat creates a genuine vacuum for an independent, opinionated neighborhood product. But the graveyard of companies that tried to fill similar gaps — Localize.city ($70M raised, shut down August 2024), Crystal Roof (five years old, still two people), AreaVibes (16 years old, declining traffic) — reveals structural challenges that honest data alone won't solve. The strongest evidence from this research: no one has successfully built an independent, consumer-facing, comprehensive neighborhood evaluation product at scale. The reasons are distribution, monetization, and regulatory risk — not data availability. Data is abundant. The hard part is everything else.

## Part 1: The data source landscape

### Health and environmental risk — the richest free data dimension

This is NestCheck's strongest differentiation opportunity. Most proptech focuses on climate/natural disaster risk (flood, fire, wind); almost no consumer product integrates health hazard proximity data. The environmental site assessment industry (EDR, EDM) serves commercial due diligence but doesn't offer consumer-facing, address-level health risk scoring.

#### Tier 1 hazards: strong evidence, good data availability

High-traffic roads have the most robust evidence base of any residential health hazard. The CDC documented that 11 million Americans live within 150 meters of a major highway, where traffic-related air pollution (TRAP) is associated with asthma exacerbation, cardiovascular mortality, and impaired lung function. The Health Effects Institute's 2010 panel found "sufficient" evidence for causation. Emissions typically diminish to background levels within 150–300 meters. The data source is the FHWA Highway Performance Monitoring System (HPMS), which provides Annual Average Daily Traffic (AADT) counts at road-segment level for all public roads nationally, available as free shapefiles. OpenStreetMap road classification provides a supplementary layer.

Gas station benzene exposure has moderate-to-strong evidence. Hilpert et al. (2019) at Columbia/Johns Hopkins found vent pipe emissions 10x higher than California's estimates used for setback regulations, with California's benzene reference exposure level exceeded at 160 meters at a Midwest station. California recommends 300-foot setbacks for large stations; Maryland requires 500 feet. The EPA UST Finder contains 2.2 million active/historic tanks across 800,000 facilities with point-level coordinates, available free at gispub.epa.gov/ustfinder. State UST registries (California's GeoTracker, NY DEC) are often more current.

Superfund and industrial contamination has well-established links to cancer, neurological effects, and birth defects. The EPA's SEMS database (replacing CERCLIS in 2014) contains ~1,300+ NPL sites and thousands of non-NPL sites with boundary polygons, updated every two hours. The Toxics Release Inventory (TRI) tracks releases of 800+ chemicals from ~21,000 facilities annually, accessible via a free REST API at data.epa.gov/efservice/ with no API key required and 10,000-row default responses in JSON/CSV.

Flood zones have strong evidence for property damage and mold-related health effects. The FEMA National Flood Hazard Layer covers ~90% of the US population at parcel/polygon level, with free ArcGIS REST services. First Street Foundation provides forward-looking models used by Zillow and Redfin.

#### Tier 2 hazards: moderate evidence or contested science

Power line EMF was classified "possibly carcinogenic" (Group 2B) by IARC in 2002, based on a consistent ~2x childhood leukemia risk at exposures above 0.3–0.4 μT. EMF drops rapidly with distance: ~20 μT directly beneath lines, ~0.71 μT at 100 feet, ~0.18 μT at 200 feet. The HIFLD Transmission Lines dataset provides free national coverage of 69kV–765kV lines as GIS data. Evidence strength: moderate-contested, weakened by lack of biophysical mechanism.

Cell tower RF exposure is the most contested hazard. IARC classified RF fields as Group 2B in 2011, but ground-level exposure from towers is typically hundreds to thousands of times below FCC limits. The FCC Antenna Structure Registration database is free but incomplete — it only captures structures requiring FAA notification (generally over 200 feet or near airports). Many small cells and rooftop antennas are absent. NestCheck should include this data with appropriate caveats but should not treat it as a binary disqualifier.

Freight rail corridors present moderate noise/vibration evidence plus probabilistic hazmat transport risk. The FRA Safety Data portal and BTS National Transportation Atlas provide free national rail network GIS data.

#### The EPA EJScreen aggregation layer

EJScreen 2.3 is arguably NestCheck's single most valuable free data source. It combines 13 environmental indicators (PM2.5, ozone, diesel PM, air toxics cancer risk, traffic proximity, lead paint, Superfund proximity, RMP facility proximity, hazardous waste proximity, underground storage tanks, wastewater discharge, plus new extreme heat and drinking water layers) with demographic indicators at the census block group level. Available as bulk downloads, ArcGIS feature services, and through a web mapper — all free.

#### Key API endpoints for health dimension

|Source|Endpoint|Auth|Key limitation|
|---|---|---|---|
|EPA Envirofacts|data.epa.gov/efservice/{table}/{format}|None|10K row default|
|EPA AirNow|airnowapi.org/aq/|Free key|Real-time only|
|EPA AQS|aqs.epa.gov/data/api/|Free key|1-year max per call|
|FEMA NFHL|hazards.fema.gov/gis/nfhl/rest/services/|None|Coverage gaps in rural areas|
|FCC ASR|wireless.fcc.gov/antenna/|None|Incomplete for small cells|
|HIFLD|ArcGIS Hub downloads|None|Periodic snapshots|

### Walk quality — the hardest dimension to measure well

Walk Score measures "how easy it is to live without a car" — proximity to amenities in seven categories, using a decay function from 5-minute to 30-minute walking distance, plus pedestrian friendliness via population density, block length, and intersection density. It explicitly does not evaluate sidewalk presence, condition, shade, lighting, noise, traffic speed, perceived safety, or aesthetics. After Redfin's acquisition in October 2014 for approximately $14 million, the walkscore.com brand was maintained but innovation effectively froze. The API remains available: free tier at 5,000 calls/day, premium starting at $115/month.

The critical gap NestCheck can fill: micro-scale streetscape quality. Kim and Cho (2023, Sustainable Cities and Society) developed a walkability index combining Google Street View-derived micro-level features with macro-level metrics and validated that it outperformed Walk Score in predicting walking environment satisfaction. Larkin et al. (2022, Nature Scientific Reports) used 1.15 million GSV images across seven Canadian cities and found GSV-derived features better predicted walk-to-work rates than traditional walkability metrics.

The most promising operational framework is MAPS-Mini (Microscale Audit of Pedestrian Streetscapes, 15-item version), developed by James Sallis and colleagues at UC San Diego. It has been validated for Google Street View-based audits — not just in-person field work. Adams et al. (2022) trained EfficientNetB5 to detect eight MAPS-Mini features (sidewalks, buffers, curb cuts, crosswalks, walk signals, streetlights) from GSV images. Koo et al. (2022) automated full MAPS-Mini audits from street view with kappa statistics ranging from 0.108 to 0.897 across features.

#### Data source inventory for walk quality

OpenStreetMap sidewalk data is highly variable. A 2022 arXiv study assessed OSM sidewalk data across 50+ US cities and found inconsistent completeness and trustworthiness. Meta's Walkabout initiative contributed 56% of top-city pedestrian additions in 2024, showing heavy reliance on organized mapping campaigns. Urban cores have improving data; suburbs and rural areas remain severely underrepresented. Relevant tags include `sidewalk=*`, `highway=footway`, `footway=sidewalk`, `surface=*`, `lit=*`, and `smoothness=*`.

Street tree and canopy data comes from the NLCD Tree Canopy Cover layer at 30-meter resolution (free, annual since 1985, available at mrlc.gov) — adequate for tract-level averages but too coarse for street-level assessment. A 2025 USGS/USFS enhanced dataset applies random forest models to high-resolution land cover for 71 urban areas, adding 13.4% more canopy detection. About 40 cities participate in the USDA Forest Service Urban Forest Inventory program, but no national aggregated street tree database exists.

Pedestrian crash data at neighborhood level requires state-level databases, not federal. FARS (Fatality Analysis Reporting System) covers all fatal crashes nationally with lat/lon coordinates but misses the vast majority of pedestrian injuries (~7,500 fatalities/year vs. hundreds of thousands of injuries). CRSS provides only national estimates, not local data. States like California (SWITRS/TIMS), Florida (Signal Four), and Texas publish geocoded crash data publicly. The Safer Streets Priority Finder maintains a state-by-state directory.

Street lighting has no national database. This is a significant gap. Municipal open data covers some cities; OSM's `lit=yes/no` tag is extremely incomplete; VIIRS satellite nighttime light data at 500m resolution is far too coarse for street-level assessment. Computer vision detection from GSV is the most viable path.

The EPA National Walkability Index provides free scores (1–20) for every census block group nationally, based on intersection density, land use mix, and transit access. Useful as a baseline but too coarse for NestCheck's ambitions.

The noise gap: The US has no equivalent to the EU Environmental Noise Directive. The BTS National Transportation Noise Map covers aviation, highway, and rail noise but explicitly states it "should not be used to evaluate noise levels in individual locations." Airport noise contours (FAA Part 150) cover areas near airports only.

### Demographic and community composition — legally treacherous but data-rich

The Census Bureau's American Community Survey is the foundation. The 5-year estimates (currently 2020–2024, released December 11, 2025) are available down to block group level, which is the finest granularity for most tables. Key tables for NestCheck:

B19013 (median household income), B15003 (educational attainment), B01001 (age by sex), B25003 (tenure: owner vs. renter), B08301 (commute mode), B03002 (Hispanic origin by race)

The Census API is free with a key obtained at api.census.gov. Rate limits are 500 requests/day without a key, significantly higher with one. Data is typically 12–18 months stale at any given time.

For address-to-tract geocoding, the Census Geocoder (geocoding.geo.census.gov) is free but slow (1–5 seconds per address) and frequently experiences downtime. Geocodio ($0.50/1,000 lookups) is more reliable and returns Census geographies directly. For coordinates-to-tract, downloading TIGER/Line shapefiles and running PostGIS spatial joins in-house is the most cost-effective approach at scale.

Supplementary sources add trajectory context: IRS SOI migration data shows county-to-county flows with income attached (county-level only, free). LODES data provides census-block-level commute flows (where people live vs. work) via the LEHD program, available through the lehdr R package. USPS change-of-address aggregates are only available through expensive commercial resellers.

School data is critical for family-oriented users. GreatSchools charges for API access beyond basic directory data — numeric 1–10 ratings and themed ratings require an enterprise data license with undisclosed pricing. The free alternative is NCES Common Core of Data (100,000+ public schools, available at nces.ed.gov/ccd), which includes enrollment, demographics, and finance data but not quality ratings. The Urban Institute Education Data Portal API provides structured access.

Crime data at neighborhood level has no single national API. FBI UCR/NIBRS data is agency-level only — useless for sub-city analysis. Crime data lives in municipal open data portals (Chicago, NYC, LA, SF, Seattle publish geocoded incidents), requiring city-by-city integration with no standardized schema.

Fair Housing Act guardrails are non-negotiable. The core risk: HUD's May 2024 guidance explicitly applies FHA to digital platforms using algorithms. Key precedents include the Redfin settlement ($4 million, 2022) over minimum home price policies with disparate impact, and Meta's DOJ settlement over discriminatory ad targeting. NAR Standard of Practice 10-1 prohibits agents from volunteering information about racial/ethnic neighborhood composition. Movoto removed racial statistics from listing pages in 2009 after NFHA threatened a complaint. NeighborhoodScout continues to let users filter by racial/ethnic composition but frames it as promoting integration.

NestCheck's safest path: never commingle demographic data with property evaluations or scores. Present Census data on separate "neighborhood profile" pages, cite sources, avoid color-coding that implies quality judgments, and never create composite scores that embed protected-class-correlated variables (school ratings, crime, income) without disparate impact analysis. Engage a Fair Housing Act attorney before launch. NFHA actively monitors new platforms.

### Green space quality — beyond proximity to actual park character

The Trust for Public Land ParkServe database is the best free national resource. It provides park polygon shapefiles, service areas (10-minute walk network analysis), amenity data, and equity analysis at the census block group level for all US urban areas. Data downloads available at tpl.org/park-data-downloads. ParkScore ranks the 100 largest cities across acreage, investment, amenities, access, and equity — but city-level only. ParkServe is the underlying data layer with block-group granularity. No formal API exists; data is served via ArcGIS.

Satellite vegetation analysis via Sentinel-2 at 10-meter resolution (free from Copernicus, 5-day revisit) is ideal for neighborhood-scale assessment — it can distinguish individual park blocks, tree-lined streets, and green roofs. Google Earth Engine provides the most practical platform for computing NDVI within custom buffers around addresses, though commercial use requires Earth Engine for Enterprise. NASA's new Harmonized Landsat Sentinel-2 vegetation index products (released February 2025) offer pre-computed NDVI/EVI at 30m resolution every 2–3 days.

OpenStreetMap park amenity tags (`leisure=park`, `leisure=playground`, `amenity=toilets`, `amenity=drinking_water`, `leisure=dog_park`, `playground=slide/swing/climbing_frame`) are well-mapped for park outlines (80%+ coverage in urban areas) but poorly tagged for amenity details — only an estimated 5–10% of parks have detailed amenity sub-tags. OSM alone is insufficient for quality assessment.

Municipal park quality data is rare. NYC is the gold standard — its Parks Inspection Program conducts ~6,000 inspections/year rating parks on 16 features, published on NYC Open Data with Socrata API access. Perhaps 20–30 major US cities have meaningful park quality data in open data portals. The vast majority publish nothing beyond park locations.

Trail data: AllTrails has no public API. OpenStreetMap is the best free trail source nationally. The NPS API (developer.nps.gov) covers national parks only.

There is no national database of playground equipment or conditions. CPSC publishes safety standards, not data.

### Cross-cutting: where the defensible advantage lies

Data requiring curation, combination, or interpretation to become useful — the actual moat opportunities:

**Health hazard proximity scoring:** No consumer product combines EPA TRI + UST Finder + HPMS traffic counts + HIFLD power lines + FCC antennas + FEMA flood zones + EJScreen indicators into a single address-level health risk assessment. This integration requires domain expertise to weight hazards by evidence strength and calculate appropriate buffer distances. It is genuinely hard to replicate quickly.

**Computer vision walk quality from GSV:** Automating MAPS-Mini audits using street-level imagery creates proprietary micro-scale walkability data that no one else offers at the consumer level. This requires ML engineering investment but produces a durable advantage.

**Longitudinal neighborhood trajectory:** Computing change between ACS 5-year periods (2015–2019 vs. 2020–2024), combining with IRS SOI migration flows, LODES commute changes, and satellite NDVI trends to produce "improving/declining/stable" signals requires significant curation.

**Curated local crime data pipeline:** Building standardized city-by-city integrations across 30–50 major cities creates a meaningful barrier to entry. No API does this today.

## Part 2: Competitive autopsy

### Local Logic built the data machine but gave up the consumer relationship

Local Logic (Montreal, founded 2015) has raised approximately $20 million across seed ($1.15M CAD, 2017), Series A ($8M CAD, 2020), and Series B ($13M USD, 2023, with participation from NAR's strategic VC arm Second Century Ventures). They employ ~73 people and reach 22 million monthly users across 8,000+ real estate websites.

Their "100 billion+ data points" feed 18 proprietary Location Scores computed at the street-segment level — the stretch of road between two intersections — which is more granular than Walk Score's approach. Scores include transit-friendly, pedestrian-friendly, cycling-friendly, groceries, restaurants, nightlife, cafes, shopping, quiet, vibrant, and historic, among others. Their four-tier data acquisition strategy — open data, data partnerships (ATTOM, Crimeometer), proprietary ML-generated scores, and purchased data — is the gold standard in the space.

The lesson is stark: Local Logic solved the data problem and the distribution problem simultaneously. But their pure B2B model means no consumer knows their name despite reaching 22 million users monthly. Their scores describe characteristics (walkable, quiet, vibrant) rather than making explicit quality judgments — arguably a B2B-friendly design that avoids alienating real estate partners. Key customers include CRMLS (largest US MLS, 110K+ agents), Realtor.com, RE/MAX, Zumper, and CoreLogic.

What NestCheck should take: Local Logic's street-segment granularity and four-tier data strategy are worth emulating. But their invisible-infrastructure positioning validates NestCheck's thesis — there's an unfilled gap for a consumer-facing brand that makes opinionated judgments, not just descriptive scores.

### Localize.city is the $70 million cautionary tale

Localize.city (Israeli proptech, founded 2016) raised $70 million including a $25M Series C in 2021 led by Pitango Growth. They built an AI-driven platform using NYC open data — building violations, construction permits, environmental data, bed bug reports, rat complaints — to provide hyper-local neighborhood insights. They also built "Hunter," an AI/human concierge, and eventually pivoted to agent CRM tools (LocalizeOS, LocalizeAI, LocalizeBI).

They shut down US operations in August 2024, citing "deep crisis and uncertainty in the U.S. real estate market." Founder disputes between Winstok and Rubin added internal friction. Sister company Madlan continues operating in Israel.

The failure pattern is instructive: (1) too concentrated in NYC, unable to scale nationally because data was city-specific, (2) consumer willingness to pay was insufficient, forcing a B2B pivot to agent tools, (3) data costs were high for city-by-city expansion, (4) the 2022–2024 rate-driven market downturn was fatal because their revenue depended on transaction volume. $70 million raised with eventual shutdown should give any neighborhood data startup serious pause about burn rate versus revenue timing.

### Walk Score's acquisition froze innovation; Trulia's features were killed

Walk Score was acquired by Redfin in October 2014 for approximately $14 million (cash + stock based on SEC filings). It was Redfin's first acquisition. Pre-acquisition, Walk Score served as a data API business delivering 20 million scores per day across 30,000 partner websites. Redfin immediately increased the free API tier from 100 to 5,000 calls/day — a strategic move to lock in distribution while removing competitors' incentive to build alternatives.

The product has not significantly evolved since acquisition. It still measures only walkability, transit, and bikeability. No crime, school quality, noise, or broader neighborhood quality metrics have been added. Being owned by a brokerage aligns Walk Score's incentives with making listings look attractive, not providing hard truths.

Trulia (acquired by Zillow in February 2015 for ~$2.5 billion) was the neighborhood-first platform. It had crime maps from CrimeReports.com and SpotCrime.com, "What Locals Say" resident polls (launched March 2018), original neighborhood photography and drone footage, and demographic overlays. Zillow systematically dismantled these features: it had already removed demographic data by late 2014, and Trulia officially dropped crime data in early 2022 citing "potential for bias and inaccuracies." The reason was three-fold: Fair Housing regulatory risk, revenue model misalignment (neighborhood data that discourages buyers conflicts with agent advertising revenue), and liability from inconsistent crime data across jurisdictions.

### Nextdoor proved demand exists but crowdsourced data is toxic

Nextdoor covers approximately one-third of US households with verified-address users generating hyperlocal neighborhood discussion. Real estate is "consistently one of the most popular topics." They partnered with HouseCanary in 2018 to integrate home valuations.

They have never built a neighborhood evaluation product, primarily because crowdsourced neighborhood opinions are a bias minefield. Since 2015, Nextdoor has partnered with Stanford social psychologist Dr. Jennifer Eberhardt to redesign its crime/safety posting flow after persistent racial profiling in "suspicious person" posts. NYU research (2024) confirmed Nextdoor neighborhoods skew whiter, wealthier, older, and more educated than the general population. Academic criticism in Computational Culture argued Nextdoor's architecture could make neighborhoods "weaponized."

### AreaVibes — what 16 years of low ambition looks like

AreaVibes (founded 2009, Toronto) provides livability scores across nine categories for 45,000+ areas. It's bootstrapped, likely employing 1–5 people, with monthly traffic of ~141,000–285,000 visits (declining). Revenue comes from display advertising — the site is described as "cluttered with ads." Data sources are Census ACS (2021) and FBI UCR, updated slowly. The Great Falls Tribune called its crime data "inaccurate and some of its sourcing is suspect." Content is outsourced to TextBroker.

AreaVibes proves sustained if modest demand for livability scoring exists. But it also demonstrates that an ad-supported, SEO-first model with stale data and no investment creates a permanent lifestyle business, not a venture-scale company. BestPlaces.net (~1M monthly visits) and NeighborhoodScout (~793K) both outperform AreaVibes with similar approaches.

### Niche is the closest success story but neighborhoods are secondary

Niche (founded 2002 as College Prowler, rebranded 2013) raised $45–50 million including a $35M Series C in 2020. They have 50+ million annual users, 351 employees, and grade neighborhoods A+ through F using Census, FBI, BLS, and CDC data combined with millions of resident reviews. Revenue comes from 15,000+ school clients who pay for marketing/recruitment tools — neighborhoods are a secondary feature to their education platform.

Niche demonstrates that neighborhood data works as part of a larger platform but hasn't generated a real estate-specific business. They face criticism that selling neighborhood data to real estate companies "might reinforce neighborhood disparities based on ethnicity and income."

### The seven recurring failure patterns across all competitors

Every standalone neighborhood data company hits the same walls. Distribution is the most critical: Zillow ranks for 4.5 million+ keywords with 32.7 million monthly search visits; competing head-to-head for real estate search traffic is essentially impossible without massive marketing spend. Monetization is the second wall: consumers demonstrably want neighborhood data but will not pay for it directly — every company that tried consumer subscriptions pivoted (Walk Score to API licensing, Localize to agent tools, Niche to school marketing). Data costs and geographic scalability form the third: neighborhood data is inherently local and fragmented, making city-by-city expansion enormously expensive. Fair housing and bias risk is the fourth, actively causing the industry to retreat from neighborhood data. Acquisition by incumbents kills innovation (Walk Score frozen, Trulia features removed). Market cyclicality destroys companies dependent on transaction volume (Localize). And premature modularity means that a single modular feature like neighborhood scores can be replicated by established players.

## Part 3: Failure modes and how to avoid them

### Data dependency risk — Google's 2018 pricing shock is the precedent to fear

In July 2018, Google slashed its Maps API free quota by ~96% (from 750,000 free map loads/month to 28,000) and increased per-thousand pricing for dynamic map loads from $0.50 to $7.00 — a 1,400% increase. All access began requiring billing accounts. This drove companies like Foursquare to migrate to Mapbox.

Google restructured Maps pricing again in March 2025, replacing the universal $200/month credit with tiered models (Essentials, Pro, Enterprise) with 10,000 free billable events per SKU per month. At NestCheck's current 85–120 API calls per evaluation, estimated blended cost is $0.75–$1.20 per evaluation after free tiers are exhausted. At 100 evaluations/month, costs stay near zero. At 10,000/month, Google API costs alone reach $7,500–$12,000/month.

The mitigation strategy is clear: migrate to Mapbox for core mapping functions (Directions at $2/1K vs. Google's $5/1K, geocoding at $0.75/1K temporary vs. $5/1K, 100K free requests/month vs. 10K). Use Geocodio for Census geography lookup ($0.50/1K). Self-host Overpass for OSM queries ($200–500/month). Reserve Google's Places API only for POI data quality where alternatives fall short. A Google-free stack could reduce mapping API costs from $7,500–12,000/month at 10K evaluations to approximately $1,500–3,000/month.

Google for Startups offers up to $200K in cloud credits over two years, but these are temporary — they buy time, not structural resilience. NestCheck should treat any Google-specific credits as a bridge, not a strategy.

Walk Score API poses a different dependency risk: it's owned by Redfin (now part of Rocket Companies), a potential competitor that could restrict access at any time. Terms explicitly state Walk Score "reserves the right to change, suspend, or discontinue at any time without notice." Building an independent walkability score from OSM data + EPA National Walkability Index would eliminate this dependency, though the result would initially be less polished.

Overpass API public instances are not designed for production apps — the documentation explicitly warns against this pattern. Self-hosting or contracting with Geofabrik for commercial Overpass service is necessary before scaling beyond the validation test.

### Data quality risk — where wrong data destroys trust fastest

The highest-risk data quality failures for NestCheck:

Google Places returning incorrect POI classifications — corporate offices tagged as "parks," closed businesses still listed, gas stations mislocated. Google's POI data is generally strong for major chains but inconsistent for smaller establishments and public amenities. This matters acutely for health hazard proximity calculations where a mislocated gas station could produce a false fail.

OSM coverage gaps in suburban areas are systematic. Peer-reviewed research confirms OSM data quality correlates strongly with population density. Sidewalk data is improving in urban cores (Meta's Walkabout added 9,896 km of footways to top-10 cities in 2024) but remains "spotty" in suburbs — exactly where NestCheck's target users live. A walk quality score based on OSM in a typical suburb will miss many features, producing misleading results.

Census ACS data staleness: The current 5-year estimates (2020–2024) were released December 2025 and reflect data collected over five years. In rapidly changing neighborhoods, this data can be meaningfully wrong. Gentrifying or declining neighborhoods will show outdated income, education, and demographic profiles.

Crime data inconsistency across jurisdictions: Different agencies define, classify, and report crimes differently. A "safe" score in one city might reflect genuinely low crime or merely different reporting practices. Without normalization across jurisdictions, cross-city comparisons are unreliable. There is no national standard.

### The "good enough" problem with LLMs is real and accelerating

Zillow launched a ChatGPT integration in late 2025 — users can search real-time listings, explore neighborhoods, get pricing data, and schedule tours within ChatGPT. A $20/month ChatGPT Plus subscription with this integration delivers perhaps 70–80% of what a general consumer wants to know about a neighborhood.

Where NestCheck retains a genuine, unbridgeable advantage: structured real-time data pipelines (current flood zone status, precise EPA facility proximity, actual AADT traffic counts), block-level precision (LLMs can't reliably distinguish a great block from a bad block within the same neighborhood), standardized reproducible scoring (consistent methodology across all addresses, not stochastic text generation), and health hazard proximity with evidence-based buffer distances (LLMs don't query EPA databases and calculate benzene exposure distances).

Where the gap is merely a convenience gap that will erode: general neighborhood feel, school summaries, basic walkability descriptions, average crime perceptions, and commute estimates. LLMs are getting better at these rapidly through tool use.

NestCheck's strategic response should be to lean hard into the structured data pipeline advantages — the health hazard dimension in particular is genuinely unbridgeable by LLMs because it requires real-time spatial queries against multiple federal databases with domain-specific distance calculations.

### The distribution problem has no easy answer for DTC

Real estate SEO is among the most competitive verticals online. Zillow owns brand-name search traffic. The long-tail opportunity exists — "best neighborhoods in [City] for young families," "[Neighborhood] review" — but building authority takes 6–12+ months, and Google holds real estate content to higher YMYL (Your Money or Your Life) trustworthiness standards.

Facebook and Instagram housing ad targeting is restricted due to the 2019 FHA settlement, limiting paid acquisition options for any housing-related product. This is a distribution constraint most proptech startups underestimate.

Viable DTC distribution paths: content marketing targeting hyperlocal queries (slow but sustainable), embed/widget strategy offering free neighborhood widgets to real estate blogs and agent websites (Walk Score's original playbook), partnerships with adjacent services (relocation companies, corporate HR departments, home inspection firms, moving companies), and social media (TikTok/Instagram neighborhood comparison content for organic discovery).

The honest assessment: NestCheck will likely need to supplement DTC with some B2B component — not necessarily MLS integration that compromises honesty, but perhaps selling to relocation companies, employers with relocation budgets, or home insurance companies that benefit from honest risk assessment. The question is whether B2B can be structured so the paying customer's incentives align with honest evaluation rather than conflicting with it.

### Consumer willingness to pay lacks evidence

Carfax charges $39.99/single report or $99.99/year for unlimited reports and generates an estimated $400–500M annually. But the analogy breaks down critically: Carfax has proprietary data (VIN history records from 130,000+ sources) with no free substitute. Neighborhood data is widely available for free from multiple sources. Additionally, Carfax's larger business is B2B dealer subscriptions, not consumer reports.

Home inspections cost $300–$500 on average with 88% buyer utilization, but inspections are often lender-required — creating quasi-mandatory demand. No one requires a neighborhood report.

I found no evidence of consumers paying for standalone neighborhood reports at scale. Every company that tried this pivoted: AreaVibes to ads, Localize to agent tools, Walk Score to API licensing, Niche to school marketing, Neighborhoods.com to agent referral fees.

A realistic price point for a NestCheck report is likely $5–15 per report (impulse-buy range) or $20–40/month for unlimited searches during an active home search. The narrow conversion window (3–6 months of active searching) makes subscription economics challenging. B2B revenue — from agents, lenders, relocation firms, or insurers — may be necessary for sustainability.

### Fair Housing Act risk requires specific architectural guardrails

HUD's May 2024 guidance explicitly applies the Fair Housing Act to digital platforms using algorithms. The Redfin settlement ($4M, 2022) demonstrated that even well-intentioned policies (minimum home price thresholds) can violate FHA through disparate impact. The Meta/DOJ settlement (2023) extended liability to algorithmic ad delivery. NAR Standard of Practice 10-1 prohibits volunteering information about neighborhood racial/ethnic composition.

NestCheck should implement these non-negotiable guardrails:

- Never display racial/ethnic demographic data alongside property evaluations, scores, or search results. This is the brightest legal line.
- Never allow filtering or sorting by demographic composition.
- Separate demographic data onto distinct "neighborhood profile" pages — not embedded in evaluation reports.
- Do not create composite scores embedding protected-class-correlated variables (school ratings, crime, income) without disparate impact testing.
- Present Census data neutrally with source attribution rather than value judgments.
- Avoid color-coding implying quality (green = good, red = bad) for any metric correlated with race or income.
- Engage a Fair Housing Act attorney before the 5-user validation test. NFHA actively monitors new platforms.

The demographic dimension of NestCheck's rubric ("objective Census data shown without judgment") is legally defensible only if architecturally separated from evaluation scores and presented with appropriate context. The legal risk is in presentation and integration, not in showing public data per se.

### Scalability versus depth — the suburban problem

NestCheck's value proposition is depth and specificity. Scaling nationally introduces predictable quality degradation:

- OSM data quality drops sharply outside urban cores, particularly for sidewalks, park amenities, and POIs
- Municipal open data (crime, park maintenance, permits) exists for perhaps 30–50 major cities; the remaining thousands of jurisdictions publish nothing
- State-level crash data varies dramatically in accessibility (some public APIs, some require formal data requests)
- Google Street View coverage is near-complete in urban/suburban areas but patchy in rural zones, limiting computer vision approaches

The practical strategy: launch in 3–5 metros where data coverage is richest (NYC, SF, Chicago, LA, Seattle all have strong open data programs), build the product with explicit "data confidence" indicators showing users where assessment is based on rich data versus sparse data, and expand metro-by-metro rather than attempting national coverage. Going from Westchester County to rural Montana will break every dimension of the product — and NestCheck should simply say so rather than generating low-confidence scores.

## Part 4: Data architecture recommendation

### Highest signal-to-effort ratio — integrate first

**Phase 1 (pre-validation, next 2 weeks):** Minimize API calls, maximize free bulk data.

Download and index these datasets locally (one-time or infrequent refresh): EJScreen block group data (all 13 environmental indicators), FEMA NFHL flood zones, HIFLD transmission lines, HPMS traffic counts, FRA rail lines, EPA TRI facility locations, EPA SEMS Superfund sites, EPA UST Finder, NLCD tree canopy cover, ParkServe park polygons and amenities, Census ACS 5-year tables (income, education, age, housing tenure, commute), EPA National Walkability Index, and Census TIGER/Line streets for block length calculations.

These are all free, national, and can be loaded into a PostGIS database for spatial queries. Most of NestCheck's health hazard dimension can be computed entirely from this local data without any API calls — point-in-polygon and distance calculations against indexed facility locations. This alone represents a substantial product.

**Phase 2 (validation test, 5 users):** Add targeted API calls for real-time layers.

Use Walk Score API (free tier, 5,000/day) for baseline walkability. Use Google Places API for gas station and POI verification (supplement EPA data with current business status). Use Census Geocoder or Geocodio for address-to-tract mapping. Use Overpass API for OSM park amenity tags and sidewalk data around the specific address. Target 20–30 API calls per evaluation rather than 85–120, using bulk-loaded local data for everything possible.

**Phase 3 (post-validation, months 2–6):** Build differentiating layers.

Integrate state-level pedestrian crash data for initial metros. Begin computer vision pipeline on Google Street View for walk quality features (start with sidewalk presence detection, tree canopy, and street lighting). Compute NDVI green quality scores from Sentinel-2 via Google Earth Engine. Build first city-specific crime data integrations (start with cities that have Socrata APIs: NYC, Chicago, SF).

### Data to defer or avoid

**Defer:** Playground equipment inventories (no data source exists), ADA compliance data (completely fragmented), comprehensive noise mapping (no adequate national source), AllTrails trail data (no API), and USPS migration data (expensive commercial product).

**Avoid or handle with extreme care:** Racial/ethnic demographic display (legal risk outweighs value for initial product), crowdsourced reviews (bias risk demonstrated by Nextdoor, Crystal Roof, AreaVibes), cell tower health scoring (contested science will invite controversy without proportionate user value), and real-time crime overlays on maps (the feature most likely to trigger Fair Housing scrutiny).

### Caching and freshness strategy

|Data type|Refresh frequency|Rationale|
|---|---|---|
|EPA facility locations (TRI, UST, Superfund)|Quarterly|Facilities change slowly; TRI updates annually|
|Census ACS demographics|Annually (December release)|5-year estimates updated yearly|
|FEMA flood zones|Semi-annually|Map revisions are infrequent|
|Walk Score|Monthly|Scores update on 6-month rolling basis|
|Google Places POI verification|Per-request with 30-day cache|Business status changes frequently|
|OSM sidewalk/park data|Monthly|Community edits accumulate|
|NDVI vegetation|Seasonal (quarterly)|Peak summer greenness most informative|
|Pedestrian crash data|Annually|State databases update annually|
|EJScreen indicators|Annually|EPA updates roughly yearly|
|HPMS traffic counts|Annually|States report annually|

### Build proprietary versus consume third-party

**Build proprietary (highest long-term value):** Health hazard proximity scoring engine (the weighting, buffer distances, and evidence-based thresholds are your intellectual property), computer vision walk quality pipeline (GSV-derived MAPS-Mini automation), composite green space quality index (NDVI + park amenity + canopy integration), and the "neighborhood trajectory" change-over-time model.

**Consume third-party (commodity data not worth recreating):** Walkability scores (Walk Score API as baseline, replace later if needed), demographic data (Census API), school ratings (GreatSchools or NCES), flood risk (FEMA NFHL), mapping and geocoding (Mapbox preferred over Google for cost).

### Minimum viable architecture for 5-user test versus 10,000 evaluations/month

**5-user validation test:** A single PostGIS database (~50GB) loaded with the Phase 1 bulk datasets, a Python/Node backend making 20–30 API calls per evaluation (Walk Score, Geocodio, Google Places for POI verification, Overpass for OSM amenities), and a simple web frontend displaying results. Total infrastructure cost: $50–100/month (small cloud server + free API tiers). No caching layer needed. No computer vision. No per-city integrations.

**10,000 evaluations/month:** PostGIS cluster with read replicas, Redis caching layer (30-day TTL for API responses), Mapbox replacing most Google API calls, self-hosted Overpass instance, computer vision pipeline (GPU instance for GSV processing, ~$500–1,000/month), city-specific crime data ETL jobs, and a CDN for map tiles. Estimated infrastructure cost: $3,000–5,000/month excluding API fees. Mapbox API costs: ~$1,500–2,000/month. Walk Score: premium tier at $115/month minimum. Total operational cost: $5,000–8,000/month.

The gap between these two architectures is large but manageable — the key insight is that the 5-user test should cost almost nothing because the highest-value data sources (EPA, FEMA, Census, HIFLD, HPMS, ParkServe, NLCD) are all free bulk downloads that can be queried locally without any API calls at all.

## Conclusion: what this research actually says about NestCheck's odds

Three findings from this research should reshape NestCheck's strategy.

First, the health hazard dimension is the strongest moat, not walkability or demographics. No consumer product today combines EPA facility databases, traffic count data, transmission line locations, flood zones, and air quality indicators into a single address-level health risk assessment with evidence-based buffer distances. This is genuinely hard to replicate, genuinely valuable to consumers, and — crucially — not compromised by LLM competition because it requires structured spatial queries against multiple federal databases. NestCheck should lead with this dimension, not treat it as one of four equal pillars.

Second, the competitive graveyard points to distribution and monetization as the killing fields, not data. Localize.city had excellent data and $70 million and still died. AreaVibes has survived 16 years on stale data because it had SEO-driven distribution. Crystal Roof has solid data and two users. The data is necessary but not sufficient. NestCheck needs a distribution hypothesis as strong as its data thesis — and the most viable options are (a) hyper-local SEO content targeting "[neighborhood] review" and "is [city] safe to live" queries, (b) a free embed/widget strategy modeled on Walk Score's pre-acquisition playbook, and (c) partnerships with relocation companies and employers whose incentives actually align with honest assessment.

Third, the regulatory environment is actively hostile to neighborhood evaluation products, and the hostility is increasing. Every data dimension except environmental risk and green space is entangled with Fair Housing Act implications. NestCheck's best regulatory posture is to lean into environmental health and walk quality as primary dimensions — these are the dimensions where honest, opinionated evaluation carries the least legal risk and the most differentiation. Demographic data should be available but architecturally separated. Crime data should be approached last and with legal counsel.

The honest assessment: NestCheck has identified a real gap. The incumbents are structurally disincentivized from filling it. The data exists to fill it well. But the 5-user validation test should focus less on "can we build this technically" (the answer is clearly yes, at low cost) and more on "will five actual homebuyers change their behavior based on this report, and would they pay $10–15 for it." That behavioral evidence is what determines whether NestCheck is a product or a project.