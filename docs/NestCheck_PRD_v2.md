

**NESTCHECK**

Product Requirements Document

*Unbiased neighborhood intelligence for the decisions that shape your life.*

**Author:** Jeremy Browning

**Date:** February 17, 2026

**Status:** Draft v2.0 (Research-Informed Revision)

**Stage:** Pre-seed / Solo founder

*Confidential*

# **Thesis**

The people with distribution in real estate are structurally disincentivized from giving honest neighborhood evaluations. Listing platforms optimize for transactions, not truth. Agents have financial stakes in closing deals. Crowdsourced opinions devolve into bias expression. NestCheck bets that a machine-driven evaluation methodology, built on objective data with an opinionated but transparent rubric, produces more honest and less biased neighborhood judgment than any of these alternatives.

**The magic sentence:** We are betting that an opinionated, health-first, consumer-facing neighborhood evaluation tool will become the trusted standard for residential decision-making, because nobody currently serving this market has the structural incentive to tell buyers the truth about where they are choosing to live.

| Research reality check: No one has successfully built an independent, consumer-facing, comprehensive neighborhood evaluation product at scale. The reasons are distribution, monetization, and regulatory risk. Data is abundant. The hard part is everything else. This PRD is written with that graveyard in full view. |
| :---- |

# **The Root Problem**

NestCheck exists because of a structural misalignment in the real estate information ecosystem. The root problem is not that neighborhood data is hard to find. It is that the entities with distribution are financially incentivized to obscure or soften it.

### **Why Chain**

Why do homebuyers do extensive manual research on Google Maps before committing to a property? Because listing platforms like Zillow and Redfin optimize for the property, not the neighborhood. The property is the transaction. The neighborhood is the life.

Why don't listing platforms solve this? Because their business model is lead generation for agents. They are incentivized to get users to click "Contact Agent," not to surface information that might cause a buyer to walk away. Honest neighborhood data is sometimes anti-transactional.

Why does this matter? Because the cost of a bad neighborhood decision is enormous. It affects health, commute, childhood quality, daily wellbeing, and financial outcomes. A $3,000/month apartment next to a gas station is a health hazard that no listing will disclose.

**The incumbents are actively retreating from this space.** Trulia killed its crime maps in 2022\. Zillow removed demographic data. Redfin publicly refused to add crime information. This retreat creates a genuine vacuum for an independent, opinionated neighborhood product.

# **Strategic Direction**

Three paths were evaluated. One was chosen.

### **Path A: AI-Native Infrastructure (Not Chosen)**

Build the data layer so AI agents can consume neighborhood insights programmatically. Rejected because defensibility is low. Any LLM with tool use can stitch together Google Maps, Walk Score, and Census APIs directly. NestCheck's value is not data aggregation; it is the judgment layer, and judgment layers are difficult to sell as infrastructure.

### **Path B: B2B to Realtors/MLS (Not Chosen)**

Sell neighborhood insights to brokerages and MLS platforms, following the Local Logic model. Rejected because this path contains a structural tension: selling honest neighborhood insights to people whose business depends on closing transactions requires softening the product's sharpest edge. Local Logic solved the data problem and the distribution problem simultaneously but remains invisible to consumers despite reaching 22 million monthly users. Their scores describe characteristics rather than making explicit quality judgments, which is a B2B-friendly design that avoids alienating real estate partners.

### **Path C: Consumer Product With Aligned B2B (Chosen)**

Build a direct-to-consumer neighborhood evaluation tool as the primary product identity, supplemented by B2B partnerships where the paying customer's incentives align with honest evaluation.

Why chosen: The core problem can only be solved when the entity providing judgment has no financial stake in the transaction. A consumer product is the only path where NestCheck's incentives are fully aligned with the user's.

**Research-informed refinement:** The original strategic decision framed this as a hard binary: consumer product with no B2B. The competitive evidence shows that every consumer-only neighborhood data company either died (Localize.city, $70M raised, shut down August 2024\) or became a lifestyle business (AreaVibes, 16 years old, declining traffic). The revised strategy maintains consumer-facing as the primary identity but permits B2B partnerships with entities whose incentives align with honest assessment: relocation companies, corporate HR departments, home insurers, and home inspection firms. These partners want honest neighborhood evaluation. MLS and brokerage partnerships remain excluded.

| STRATEGIC DECISION Decision: Consumer product as primary identity. B2B permitted only where partner incentives align with honest evaluation. MLS/brokerage partnerships excluded. Rationale: Consumer-only companies in this space die from distribution and monetization failures. But B2B that requires softening insights kills the product's core value. The middle path: consumer-facing brand with aligned B2B revenue. |
| :---- |

# **Competitive Landscape**

The competitive evidence reveals seven recurring failure patterns: distribution costs (Zillow ranks for 4.5M+ keywords), consumer unwillingness to pay (every company that tried pivoted), geographic scalability costs, Fair Housing regulatory risk, acquisition freezing innovation, market cyclicality, and premature modularity. NestCheck's strategy must address each.

| Competitor | What They Do | Structural Limitation | NestCheck Edge |
| :---- | :---- | :---- | :---- |
| Local Logic | 85B+ data points, neighborhood reports for MLS/brokerages, \~73 employees | B2B model requires softening insights; invisible to consumers despite 22M monthly users | Consumer-facing brand making opinionated judgments, not just descriptive scores |
| Localize.city (Dead) | AI-driven NYC neighborhood insights; raised $70M; shut down Aug 2024 | Too concentrated in NYC; consumer WTP insufficient; forced B2B pivot; market downturn fatal | Health-first differentiation with national bulk data; lean cost structure |
| AreaVibes | Livability scores for 45K+ areas; 16 years old; declining traffic | Stale data (Census 2021, FBI UCR); ad-cluttered; no investment; questioned accuracy | Fresh data pipelines, evidence-based methodology, health dimension |
| Walk Score (Redfin/Rocket) | Walkability, transit, and bike scores; 20M scores/day | Frozen since 2014 acquisition; proximity only, not experience; owned by competitor | Walk quality evaluation via MAPS-Mini, not just proximity metrics |
| Niche | $45-50M raised; 50M+ annual users; A+ to F grades | Neighborhoods secondary to education platform; school marketing revenue model | Neighborhood-first, health-first evaluation |
| Zillow/Redfin | Dominant listing platforms; some neighborhood data | Lead-gen model; actively removing neighborhood data (Trulia crime maps killed 2022\) | No transaction incentive; honesty is the product |
| ChatGPT \+ Zillow | Real-time listing search, neighborhood info via $20/mo subscription | No structured spatial queries; cannot reliably distinguish block-level variation; stochastic output | Reproducible scoring, EPA database queries, evidence-based buffer distances |

# **Moat: Where NestCheck Is Defensible vs. Where the Gap Erodes**

The most immediate competitive threat is not another proptech tool. It is a user opening ChatGPT or Claude and asking "evaluate this neighborhood for me." The moat argument must distinguish between durable advantages and temporary convenience gaps.

### **Durable Advantages (LLMs Cannot Replicate)**

Structured real-time data pipelines querying current flood zone status, precise EPA facility proximity calculations, and actual AADT traffic counts against multiple federal databases. Block-level precision that distinguishes a great block from a bad block within the same neighborhood. Standardized reproducible scoring with consistent methodology across all addresses. Health hazard proximity calculations with evidence-based buffer distances derived from peer-reviewed research. These require spatial queries against indexed PostGIS databases, not text generation.

### **Temporary Convenience Gaps (Will Erode)**

General neighborhood feel, school summaries, basic walkability descriptions, average crime perceptions, and commute estimates. LLMs are getting better at these rapidly through tool use. NestCheck should not build its positioning around these dimensions.

### **Strategic Response**

Lead with the structured data pipeline advantages. The health hazard dimension in particular is genuinely unbridgeable by LLMs because it requires real-time spatial queries against multiple federal databases with domain-specific distance calculations. The convenience gap dimensions (school summaries, general feel) should be included for completeness but not positioned as differentiators.

# **The Rubric: Health-First, Evidence-Based, User-Steerable**

**NestCheck's rubric is the product.** It encodes a specific worldview about what makes a neighborhood livable. Unlike the original four-pillar structure that treated all dimensions equally, the rubric now reflects the research finding that health hazard proximity is the strongest moat, not one of four equal pillars. The hierarchy is explicit: health is the foundation; walkability and green space are strong differentiators; demographics are contextual information presented separately.

## **Tier Zero: Health Risk Proximity (Primary Differentiator, Strongest Moat)**

**The position:** Your home should not slowly make you sick, and we will tell you if it will.

No consumer product today combines EPA facility databases, traffic count data, transmission line locations, flood zones, and air quality indicators into a single address-level health risk assessment with evidence-based buffer distances. This is genuinely hard to replicate, genuinely valuable to consumers, and not compromised by LLM competition. NestCheck leads with this dimension.

### **Evidence-Based Disqualifier Thresholds**

Each threshold is derived from peer-reviewed research and regulatory precedent, not arbitrary distances. The rubric applies tiered gates based on evidence strength.

| Hazard | Buffer Distance | Evidence Basis | Gate Type |
| :---- | :---- | :---- | :---- |
| High-traffic roads (AADT \> 50K) | 150-300 meters | CDC: 11M Americans live within 150m of major highways; HEI 2010 panel found "sufficient" evidence for causation; emissions diminish to background at 150-300m | Hard fail within 150m; warning at 150-300m |
| Gas stations | 150-500 feet | Hilpert et al. (2019, Columbia/JHU): benzene reference level exceeded at 160m; California recommends 300ft setbacks; Maryland requires 500ft | Hard fail within 300ft; warning at 300-500ft |
| Superfund/NPL sites | Varies by contaminant | EPA SEMS database; well-established links to cancer, neurological effects, birth defects | Hard fail if within EPA-defined remediation boundary |
| FEMA flood zones | Zone designation | Strong evidence for property damage and mold-related health effects; FEMA NFHL coverage \~90% of US population | Hard fail in Zone A/V; warning in Zone X (shaded) |
| TRI facilities | Site-specific | EPA TRI tracks 800+ chemicals from \~21,000 facilities; risk depends on chemical type and release volume | Warning based on chemical-specific risk and proximity |
| Power lines (69kV+) | 100-200 feet | IARC Group 2B ("possibly carcinogenic"); \~2x childhood leukemia risk above 0.3-0.4 uT; EMF drops to \~0.18 uT at 200ft | Warning only (evidence moderate-contested) |

| Cell towers: The original PRD listed cell towers as aspirational disqualifiers. The research advises against this. IARC classified RF fields as Group 2B, but ground-level exposure from towers is typically hundreds to thousands of times below FCC limits, and the FCC Antenna Structure Registration database is incomplete. Include with appropriate caveats but do not treat as a binary disqualifier. |
| :---- |

### **Primary Data Sources for Health Dimension**

The health dimension can be computed almost entirely from free, bulk-downloadable federal datasets loaded into a PostGIS database for spatial queries, with no API calls required for most calculations.

| Source | What It Provides | Access |
| :---- | :---- | :---- |
| EJScreen 2.3 | 13 environmental indicators (PM2.5, ozone, diesel PM, air toxics cancer risk, traffic proximity, lead paint, Superfund proximity, RMP proximity, hazardous waste, UST, wastewater, plus extreme heat and drinking water) at census block group level | Free bulk download \+ ArcGIS services |
| EPA TRI | 800+ chemical releases from \~21,000 facilities | Free REST API at data.epa.gov/efservice/ (no key, 10K rows default) |
| EPA UST Finder | 2.2M active/historic tanks across 800K facilities with point coordinates | Free at gispub.epa.gov/ustfinder |
| EPA SEMS | \~1,300+ NPL sites plus thousands of non-NPL sites with boundary polygons | Free, updated every 2 hours |
| FHWA HPMS | Annual Average Daily Traffic counts at road-segment level for all public roads | Free shapefiles |
| FEMA NFHL | Flood zone designations at parcel/polygon level | Free ArcGIS REST services |
| HIFLD Transmission Lines | 69kV-765kV power lines nationally | Free GIS data |

**EJScreen 2.3 is NestCheck's single most valuable free data source.** It pre-combines 13 environmental indicators with demographic data at the census block group level and is available as bulk downloads, ArcGIS services, and through a web mapper.

| RUBRIC DECISION: HEALTH DISQUALIFIERS Decision: Evidence-tiered pass/fail gates on health risk proximity. Hard fails for Tier 1 hazards with strong evidence. Warnings for Tier 2 hazards with moderate or contested evidence. No composite scoring that dilutes signal. Rationale: Health hazards are not tradeoffs. A great school district does not offset benzene exposure. The rubric reflects this by making health proximity a tier-zero gate, with thresholds derived from peer-reviewed research and regulatory precedent rather than arbitrary distances. |
| :---- |

## **Tier One: Walk Quality Over Walk Score**

**The position:** Walkability is not a proximity metric. It is an experience metric.

Walk Score measures "how easy it is to live without a car" using proximity to amenities with a decay function. It explicitly does not evaluate sidewalk presence, condition, shade, lighting, noise, traffic speed, perceived safety, or aesthetics. After Redfin's acquisition in 2014 for approximately $14 million, innovation effectively froze. The product has not significantly evolved.

### **Operationalization: MAPS-Mini Framework**

The most promising operational framework is MAPS-Mini (Microscale Audit of Pedestrian Streetscapes, 15-item version), developed by James Sallis and colleagues at UC San Diego. It has been validated for Google Street View-based audits. Key research: Kim and Cho (2023, Sustainable Cities and Society) validated that a walkability index combining GSV-derived micro-level features with macro-level metrics outperformed Walk Score in predicting walking environment satisfaction. Adams et al. (2022) trained EfficientNetB5 to detect eight MAPS-Mini features (sidewalks, buffers, curb cuts, crosswalks, walk signals, streetlights) from GSV images.

This is a Phase 3 investment (months 2-6 post-validation), not a launch requirement. For the 5-user validation test, Walk Score API (free tier, 5,000 calls/day) provides an adequate baseline. The proprietary walk quality layer built on MAPS-Mini and GSV computer vision becomes a durable differentiator over time.

### **Data Quality Warning: The Suburban Gap**

OpenStreetMap sidewalk data is highly variable. A 2022 arXiv study found inconsistent completeness across 50+ US cities. Urban cores have improving data (Meta's Walkabout added 9,896 km of footways to top-10 cities in 2024), but suburbs remain severely underrepresented. A walk quality score based solely on OSM in a typical suburb will miss many features. NestCheck must include explicit "data confidence" indicators showing users where assessments are based on rich data versus sparse data.

## **Tier One: Green Space Quality, Not Just Quantity**

**The position:** A park on the map is not the same as a park you would use.

Most tools count parks. NestCheck evaluates park utility: loop trails for running, fenced areas for young children, shade coverage, playground equipment, maintenance quality. The Trust for Public Land ParkServe database provides park polygon shapefiles, service areas (10-minute walk network analysis), amenity data, and equity analysis at the census block group level for all US urban areas. Sentinel-2 satellite imagery at 10-meter resolution enables NDVI vegetation analysis within custom buffers around addresses.

The gap: only an estimated 5-10% of parks in OSM have detailed amenity sub-tags. Municipal park quality data exists for perhaps 20-30 major US cities (NYC is the gold standard with \~6,000 inspections/year). There is no national database of playground equipment or conditions. NestCheck should acknowledge these gaps transparently rather than generating low-confidence scores.

## **Contextual Layer: Demographic Composition**

**The position:** Users declare what they are looking for. The rubric provides objective data. It does not judge.

NestCheck surfaces demographic data from the Census Bureau's American Community Survey because it is genuinely useful for homebuyers. A family with a toddler benefits from knowing whether neighbors have children of similar age.

**Critical change from v1:** Demographic data is now architecturally separated from evaluation scores rather than presented as one of four equal rubric pillars. This is a legal necessity, not just a design preference. HUD's May 2024 guidance explicitly applies the Fair Housing Act to digital platforms using algorithms. The Redfin settlement ($4M, 2022\) demonstrated that even well-intentioned policies can violate FHA through disparate impact.

| RUBRIC DECISION: DEMOGRAPHICS Decision: Show objective Census data on separate "neighborhood profile" pages. Never display alongside property evaluations or scores. Never allow filtering or sorting by demographic composition. Never create composite scores embedding protected-class-correlated variables. Rationale: Demographic data is useful. Demographic judgment is dangerous. Architectural separation is the only legally defensible posture. NFHA actively monitors new platforms. |
| :---- |

# **Fair Housing Act: Architectural Guardrails (Non-Negotiable)**

The regulatory environment is actively hostile to neighborhood evaluation products. Every data dimension except environmental risk and green space is entangled with Fair Housing Act implications. These guardrails are architectural requirements, not guidelines.

1. Never display racial/ethnic demographic data alongside property evaluations, scores, or search results. This is the brightest legal line.

2. Never allow filtering or sorting by demographic composition.

3. Separate demographic data onto distinct "neighborhood profile" pages, not embedded in evaluation reports.

4. Do not create composite scores embedding protected-class-correlated variables (school ratings, crime, income) without disparate impact testing.

5. Present Census data neutrally with source attribution rather than value judgments.

6. Avoid color-coding implying quality (green \= good, red \= bad) for any metric correlated with race or income.

7. Engage a Fair Housing Act attorney before the 5-user validation test, not before launch. NFHA actively monitors new platforms.

NestCheck's safest dimensions are environmental health and walk quality. These are the dimensions where honest, opinionated evaluation carries the least legal risk and the most differentiation. Crime data should be approached last and with legal counsel. The demographic dimension is legally defensible only if architecturally separated from evaluation scores.

# **Key Product Decision: Opinionated Rubric With User Steering**

A critical fork: whether NestCheck is a configurable scoring engine (users set their own weights) or an opinionated evaluator (the rubric tells you what matters). The answer is both, layered.

**Layer 1: Non-negotiable disqualifiers.** Health risk proximity gates are opinionated and binary. Users cannot configure these away. A property within 300 feet of a gas station fails regardless of user preferences. This is the editorial voice of the product.

**Layer 2: Weighted evaluation.** Beyond disqualifiers, the rubric evaluates walkability, green space, transit, schools, and other factors with default weights informed by health research and livability frameworks (AARP, Jan Gehl, 20-minute neighborhood concept).

**Layer 3: User steering.** Users can adjust the relative importance of factors beyond the disqualifier tier. A remote worker who never commutes can de-weight transit. A family with school-age children can increase school weighting. The rubric adapts while maintaining its health-first foundation.

# **Geographic Scope: Metro-by-Metro, Not National**

Data quality degrades sharply outside urban cores. OSM sidewalk data, municipal crime data, park quality data, and pedestrian crash data are all concentrated in major metros. Attempting national coverage at launch will produce misleading scores in suburbs and rural areas.

### **Launch Markets (3-5 Metros)**

NYC, San Francisco, Chicago, Los Angeles, and Seattle all have strong open data programs, Socrata-accessible APIs, geocoded crime incident data, and good OSM coverage. These five metros cover a large share of NestCheck's likely early adopter market.

### **Data Confidence Indicators**

Every evaluation must include explicit data confidence indicators showing users where the assessment is based on rich data versus sparse data. A score for a Manhattan address with 13 EJScreen indicators, city-level crime data, 6,000 annual park inspections, and dense OSM coverage is categorically different from a score for a suburban Texas address with only federal bulk data. NestCheck should communicate this honestly rather than generating uniform-looking scores of varying reliability.

### **Expansion Strategy**

Expand metro-by-metro as city-specific data integrations are built. Each new metro requires: crime data pipeline integration, pedestrian crash data source identification, park quality data assessment, and OSM coverage evaluation. Going from Westchester County to rural Montana will break every dimension of the product. NestCheck should say so rather than generating low-confidence scores.

# **Distribution Strategy**

**The competitive graveyard points to distribution and monetization as the killing fields, not data.** Localize.city had excellent data and $70 million and still died. AreaVibes has survived 16 years on stale data because it had SEO-driven distribution. Crystal Roof has solid data and essentially no users. Data is necessary but not sufficient.

### **Viable Channels**

**Hyper-local SEO content (slow but sustainable):** Target long-tail queries like "\[neighborhood\] review," "is \[city\] safe to live," "best neighborhoods in \[city\] for young families." Real estate SEO is among the most competitive verticals online, and Google holds real estate content to higher YMYL trustworthiness standards. Building authority takes 6-12+ months. But this is how AreaVibes survives despite everything else being weak.

**Free embed/widget strategy (Walk Score's original playbook):** Offer free neighborhood health score widgets to real estate blogs, agent websites, and relocation company sites. Walk Score built distribution by serving 20 million scores per day across 30,000 partner websites before its acquisition. Redfin then increased the free API tier to lock in distribution. This playbook is proven.

**Aligned B2B partnerships:** Relocation companies, corporate HR departments with relocation budgets, home inspection firms, and home insurance companies all benefit from honest neighborhood risk assessment. These partners' incentives align with truthful evaluation, unlike MLS partnerships. This supplements DTC; it does not replace it.

**Social media (organic):** TikTok and Instagram neighborhood comparison content for organic discovery. "We evaluated this $3,000/month apartment and here's what we found 400 feet away" is inherently shareable content.

### **Distribution Constraint**

Facebook and Instagram housing ad targeting is restricted due to the 2019 FHA settlement, limiting paid acquisition options for any housing-related product. Most proptech startups underestimate this constraint. NestCheck's distribution must be primarily organic and partnership-driven, not paid social.

# **Monetization Hypothesis**

| Research reality check: No evidence exists of consumers paying for standalone neighborhood reports at scale. Every company that tried pivoted: AreaVibes to ads, Localize to agent tools, Walk Score to API licensing, Niche to school marketing, Neighborhoods.com to agent referral fees. The Carfax analogy breaks down because Carfax has proprietary VIN history data with no free substitute, while neighborhood data is widely available for free. This section reflects that evidence. |
| :---- |

### **Revenue Model (Hypothesis, Requires Validation)**

**Tier 1 (Free):** High-level pass/fail on health disqualifiers for any address. Enough to demonstrate value and create the "I need to see more" moment. This may be the permanent state for most users.

**Tier 2 (Single Report, $10-15):** Full evaluation for one address including all rubric layers, detailed scoring, and comparison to surrounding neighborhoods. Priced at impulse-buy range, below the original $15-25 target, reflecting the absence of evidence for higher price points.

**Tier 3 (Search Subscription, $30-50/month):** Unlimited evaluations during an active home search window (30/60/90 days). The narrow conversion window (3-6 months of active searching) makes subscription economics challenging.

**Tier 4 (B2B Licensing):** Sell health risk evaluation data to relocation companies, corporate HR departments, home insurers, and home inspection firms. These buyers have budgets for honest neighborhood assessment and incentives aligned with NestCheck's product. This is likely necessary for sustainability based on competitive evidence.

### **Validation Questions for Monetization**

The 5-user validation test must specifically pressure-test willingness to pay. The two critical questions: (1) Did this report tell you something you did not already know? (2) Would you have paid $10-15 for this before making your decision? If fewer than 2 of 5 say yes to the second question, the consumer monetization hypothesis needs revision and B2B becomes the primary revenue path.

# **Data Architecture: Phased Build**

The key insight from the research: the 5-user test should cost almost nothing because the highest-value data sources are all free bulk downloads that can be queried locally without any API calls.

## **Phase 1: Pre-Validation (Next 2 Weeks)**

Minimize API calls, maximize free bulk data. Download and index these datasets into a single PostGIS database (\~50GB):

| Dataset | What It Provides | Refresh Frequency |
| :---- | :---- | :---- |
| EJScreen block group data | All 13 environmental indicators | Annually |
| FEMA NFHL flood zones | Flood zone designations | Semi-annually |
| HIFLD transmission lines | 69kV-765kV power lines | Periodic snapshots |
| FHWA HPMS traffic counts | AADT at road-segment level | Annually |
| FRA rail lines | National rail network | Periodic |
| EPA TRI facility locations | Chemical release facilities | Quarterly |
| EPA SEMS Superfund sites | NPL and non-NPL sites | Updated every 2 hours |
| EPA UST Finder | Underground storage tanks | Quarterly |
| NLCD tree canopy cover | 30m resolution canopy data | Annually |
| ParkServe park polygons | Park boundaries, service areas, amenities | Annually |
| Census ACS 5-year tables | Income, education, age, housing tenure, commute | Annually (Dec release) |
| EPA National Walkability Index | Walkability scores 1-20 per block group | Periodic |
| Census TIGER/Line streets | Street network for block length calculations | Annually |

Most of NestCheck's health hazard dimension can be computed entirely from this local data: point-in-polygon tests and distance calculations against indexed facility locations. This alone represents a substantial product.

**Estimated infrastructure cost:** $50-100/month (small cloud server \+ free API tiers).

## **Phase 2: Validation Test (5 Users)**

Add targeted API calls for real-time layers. Target 20-30 API calls per evaluation rather than 85-120, using bulk-loaded local data for everything possible.

| API | Purpose | Cost |
| :---- | :---- | :---- |
| Walk Score API | Baseline walkability (free tier) | Free (5,000 calls/day) |
| Geocodio | Address-to-tract mapping | $0.50/1,000 lookups |
| Google Places API | Gas station and POI verification | Per-request (within free tier at 5 users) |
| Overpass API (self-hosted before scale) | OSM park amenity tags and sidewalk data | Free public instances for validation only |

## **Phase 3: Post-Validation (Months 2-6)**

Build differentiating layers: state-level pedestrian crash data for initial metros, computer vision pipeline on Google Street View for MAPS-Mini walk quality features (sidewalk presence, tree canopy, street lighting), NDVI green quality scores from Sentinel-2, and first city-specific crime data integrations (NYC, Chicago, SF via Socrata APIs). Estimated infrastructure cost at 10,000 evaluations/month: $5,000-8,000/month including API fees.

### **Data Dependency Mitigation**

Google's 2018 Maps API pricing shock (1,400% increase) is the precedent to fear. Walk Score API is owned by Redfin (now Rocket Companies), a potential competitor that could restrict access at any time. The mitigation strategy: migrate to Mapbox for core mapping (Directions at $2/1K vs. Google's $5/1K, 100K free requests/month vs. 10K), use Geocodio for Census geography, self-host Overpass for OSM queries, and reserve Google Places only for POI data quality where alternatives fall short. Build an independent walkability score from OSM \+ EPA Walkability Index to eliminate Walk Score dependency over time. Treat any Google for Startups credits ($200K over two years) as a bridge, not a strategy.

# **Positioning**

### **What NestCheck Is**

A health-first neighborhood evaluation tool that tells you what listings, agents, and crowdsourced reviews will not. Supplementary to the traditional real estate process, not adversarial to it. The Carfax of neighborhoods.

### **What NestCheck Is Not**

Not a listing platform, not a lead generation tool, not a social network, and not a replacement for a real estate agent. It does not sell properties or connect buyers with agents. Its only product is honest, structured judgment about where you are considering living.

### **Tagline Options**

"Know before you go." / "The neighborhood report your agent won't give you." / "Unbiased neighborhood intelligence for the decisions that shape your life."

# **Validation Plan**

Before building further, the core value proposition must be tested with real users evaluating real addresses. The research is clear: the 5-user test should focus less on "can we build this technically" (the answer is clearly yes, at low cost) and more on "will five actual homebuyers change their behavior based on this report, and would they pay $10-15 for it."

### **Test A: Prospective Evaluation**

Evaluate five real addresses for five real people who are actively considering those addresses. After delivering the evaluation, ask: (1) Did this tell you something you did not already know? (2) Would you have paid for this before making your decision?

### **Test B: Ground-Truth Accuracy (Equal Priority)**

Run the evaluation against addresses where someone already lives and knows the ground truth. Ask them to grade accuracy dimension by dimension. If the synthesis is wrong about neighborhoods people already live in, it will be wrong about neighborhoods they are considering. This is a faster, harder, more honest test than asking house-hunters whether a report "changed their thinking."

### **Falsification Criteria**

If fewer than 3 of 5 prospective test users say the evaluation told them something they did not already know, the core value proposition needs rethinking. If fewer than 2 of 5 say they would have paid, the consumer monetization hypothesis needs revision. If ground-truth accuracy tests reveal systematic errors in any dimension, that dimension needs methodology revision before launch.

### **Pre-Validation Legal Requirement**

Engage a Fair Housing Act attorney before the 5-user test, not before public launch. Review the report template, scoring methodology, and demographic data presentation for FHA compliance. NFHA actively monitors new platforms. This is a prerequisite, not an optional step.

### **Test Users**

Yaffe, Graham, Paul, Tanner, and other Columbia MBA peers who are actively in the housing market or recently made housing decisions.

# **Advisory Network**

**Data Science and Methodology:** David Guetta (Columbia network). Professional data scientist. Critical for operationalizing the MAPS-Mini walk quality pipeline, health hazard scoring methodology, and computer vision approach for GSV-derived features.

**Real Estate Domain:** Columbia Real Estate Finance Professor. Academic grounding for methodology and industry network connections.

**Fair Housing Legal Counsel:** Engage before the 5-user validation test. Required, not optional.

**Industry Founders:** Vincent-Charles Hodder (CEO, Local Logic) for market intelligence and data acquisition lessons. Vlad Suharukov and Victoria Varzinova (Crystal Roof, London) if NestCheck pursues European expansion.

# **Appendix: Decision Log**

This section captures key judgment calls. When facing a fork in the road, refer here before re-litigating settled decisions.

| DECISION 1: GO-TO-MARKET Decision: Consumer product as primary identity, with B2B partnerships where partner incentives align with honest evaluation. MLS/brokerage partnerships excluded. Rationale: Consumer-only companies die from distribution and monetization failures ($70M Localize.city). B2B that softens insights kills the product. The middle path: consumer brand with aligned B2B. |
| :---- |

| DECISION 2: RUBRIC HIERARCHY Decision: Health hazard proximity is the primary differentiator and tier-zero gate, not one of four equal pillars. Walkability and green space are tier-one differentiators. Demographics are contextual, architecturally separated. Rationale: Research shows health is the strongest moat (hardest to replicate, least legal risk, genuinely unbridgeable by LLMs). Equal-weight pillars dilute the strongest signal. |
| :---- |

| DECISION 3: CROWDSOURCED DATA Decision: Machine-driven evaluation only. No user-generated neighborhood reviews. Rationale: Unstructured human opinion about neighborhoods degenerates into bias expression. Nextdoor is the proof case. Academic research (NYU 2024\) confirms Nextdoor neighborhoods skew whiter, wealthier, older, and more educated. |
| :---- |

| DECISION 4: DEMOGRAPHIC HANDLING Decision: Surface objective Census data on separate pages. Never display alongside evaluation scores. Never allow filtering by composition. Never embed in composite scores. Rationale: HUD May 2024 guidance, Redfin $4M settlement, Meta DOJ settlement. Architectural separation is the only legally defensible posture. |
| :---- |

| DECISION 5: POSITIONING Decision: Supplementary to agents (Carfax model), not adversarial. Rationale: Adversarial positioning gets press but locks out distribution. Supplementary positioning creates a trusted tool alongside the traditional process. |
| :---- |

| DECISION 6: GEOGRAPHIC SCOPE Decision: Launch in 3-5 metros with richest data ecosystems (NYC, SF, Chicago, LA, Seattle). Expand metro-by-metro. Include data confidence indicators. Rationale: Data quality degrades sharply outside urban cores. National coverage at launch produces misleading scores. Acknowledge gaps honestly rather than generating uniform-looking scores of varying reliability. |
| :---- |

| DECISION 7: HEALTH THRESHOLDS Decision: Evidence-based buffer distances derived from peer-reviewed research and regulatory precedent, tiered by evidence strength. No single arbitrary distance. Rationale: Hilpert et al. 2019, HEI 2010 panel, CDC documentation, California/Maryland regulatory setbacks. Thresholds must be defensible when challenged. |
| :---- |

# **Why This Matters Beyond the Product**

*"I just want to build things that nobody can take from me."*

NestCheck exists at the intersection of personal conviction and professional expertise. It was born from direct experience with the frustration of manual neighborhood evaluation, refined through eight years of building personalization and recommendation systems at Pinterest, Twitter, and Uber, and motivated by the realization that achievement within institutions is revocable but ownership of what you build is not.

Nobody can take your degrees. Nobody can take your relationships. Nobody can take the judgment you have built over a career. And nobody can take NestCheck.