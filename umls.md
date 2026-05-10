# Enolix Outreach System (EOS) — Diagram Prompt Guide
### Standardised Names, Descriptions & AI Image Prompts for All UML Diagrams

---

## SECTION 1 — Canonical Actor & Class Names

> **Rule:** Every diagram must use exactly these names. No abbreviations, no variations. Consistency across all diagrams is mandatory.

### Human Actors (Users)

| Canonical Name | Role Description |
|---|---|
| **Technician** | The lead-generation operator who operates the EOS desktop app. Initiates tasks, trains the system on new sites, monitors progress, and exports leads. |
| **Admin** | Registers the system and manages access credentials. May overlap with Technician in small teams. Included for data-protection compliance. |

### System / Software Agents (Internal)

| Canonical Name | Role Description |
|---|---|
| **ExtractionCoordinator** | The central orchestrator. Receives user commands, routes tasks to WebScraper or DocumentParser, and manages the overall extraction lifecycle. |
| **WebScraper** | Fetches raw HTML from target web URLs. Executes multi-threaded exhaustive crawling across paginated directories. |
| **DocumentParser** | Handles file-based inputs (PDF, DOCX, TXT). Invokes the OCR Engine for scanned documents. |
| **DataSanitizer** | The "Self-Healing" agent. Cleans raw extracted text using regex — strips prefixes, repairs broken emails, standardises phone numbers to +254 format. |
| **MLAdapter** | Wrapper around the Groq API. Predicts pagination patterns for complex sites and infers/repairs data that DataSanitizer cannot resolve alone. |
| **StateManager** | Writes SQLite checkpoints every N records. On restart, reads the checkpoint and hands the resume index back to ExtractionCoordinator. |
| **DatabaseManager** | Single gateway to both SQLite databases. Handles all read/write operations — lead persistence, duplicate hash checks, recipe lookup, and task checkpoint management. |
| **ExportEngine** | Serialises verified leads from LeadsRepository into CSV, XLSX, or PDF files on the local file system. |

### External Systems / APIs

| Canonical Name | Role Description |
|---|---|
| **GroqAPI** | Remote cloud ML service. Receives HTML fragments and returns pagination patterns or repaired data attributes. |
| **SerperAPI** | Remote web-search API. Receives company-name queries and returns organic URLs for the WebScraper to crawl. |
| **TargetSite** | The external website or directory being scraped (e.g., Yellow Pages, industry portals). |
| **LocalFileSystem** | The technician's local disk. Receives final export files (CSV/XLSX/PDF). |

### Data Stores (Databases)

| Canonical Name | Table/File | Role Description |
|---|---|---|
| **LeadsRepository** | `leads.sqlite` | Stores all deduplicated, sanitised lead records. |
| **RecipesDB** | `recipes.sqlite` | Stores site-specific CSS selector patterns ("Site Recipes") for adaptive reuse. |
| **TaskCheckpointsDB** | table inside `leads.sqlite` | Stores task progress snapshots for recovery. |

---

## SECTION 2 — Use Case Diagram

### 2.1 Actors in This Diagram
- **Technician** (primary human actor)
- **Admin** (secondary human actor — auth & registration)
- **GroqAPI** (external system)
- **SerperAPI** (external system)
- **LeadsRepository** (data store — treated as a system boundary actor)
- **RecipesDB** (data store — treated as a system boundary actor)

### 2.2 Complete Use Case List

| Use Case ID | Name | Primary Actor |
|---|---|---|
| UC-01 | Register Account | Admin |
| UC-02 | Login | Admin / Technician |
| UC-03 | Input Target (URL or Document) | Technician |
| UC-04 | Train Visual Selector | Technician |
| UC-05 | Start Extraction Task | Technician |
| UC-06 | Monitor Live Progress | Technician |
| UC-07 | Pause / Resume Task | Technician |
| UC-08 | View Past Extractions | Technician |
| UC-09 | Browse Leads by Industry | Technician |
| UC-10 | Export Leads | Technician |
| UC-11 | Crawl Web Pages | ExtractionCoordinator → WebScraper |
| UC-12 | Parse Document (OCR) | ExtractionCoordinator → DocumentParser |
| UC-13 | Sanitise Extracted Data | DataSanitizer |
| UC-14 | Check Lead Uniqueness | DatabaseManager |
| UC-15 | Lookup Site Recipe | DatabaseManager → RecipesDB |
| UC-16 | Save Site Recipe | DatabaseManager → RecipesDB |
| UC-17 | Predict Pagination | MLAdapter → GroqAPI |
| UC-18 | Repair Malformed Data | MLAdapter → GroqAPI |
| UC-19 | Search Web for URLs | SerperAPI |
| UC-20 | Save Checkpoint | StateManager → TaskCheckpointsDB |
| UC-21 | Recover Task from Checkpoint | StateManager → ExtractionCoordinator |

### 2.3 Key Relationships

| Relationship Type | From | To | Note |
|---|---|---|---|
| `<<include>>` | UC-05 Start Extraction | UC-15 Lookup Site Recipe | Always checks DB before scraping |
| `<<include>>` | UC-05 Start Extraction | UC-11 Crawl Web Pages | Core dependency |
| `<<include>>` | UC-05 Start Extraction | UC-12 Parse Document | When input is a file |
| `<<include>>` | UC-11 Crawl Web Pages | UC-13 Sanitise Extracted Data | Every scraped record is cleaned |
| `<<include>>` | UC-13 Sanitise Data | UC-14 Check Lead Uniqueness | Cleaned data checked before save |
| `<<extend>>` | UC-17 Predict Pagination | UC-11 Crawl Web Pages | Only when pagination is complex |
| `<<extend>>` | UC-18 Repair Data | UC-13 Sanitise Data | Only when regex alone fails |
| `<<extend>>` | UC-21 Recover Task | UC-05 Start Extraction | Only when a checkpoint is found |
| `<<include>>` | UC-10 Export Leads | UC-09 Browse Leads by Industry | User filters before export |
| `<<include>>` | UC-03 Input Target | UC-19 Search Web for URLs | When input is a company name prompt |
| `<<include>>` | UC-16 Save Site Recipe | UC-04 Train Visual Selector | Recipe saved after training |
| `<<include>>` | UC-20 Save Checkpoint | UC-05 Start Extraction | Periodic checkpointing during task |

### 2.4 Image Generation Prompt

```
Create a clean UML Use Case Diagram for a software system called "Enolix Outreach System (EOS)".

SYSTEM BOUNDARY: Draw a large rectangle labelled "Enolix Outreach System Boundary" in the centre of the image.

ACTORS (draw as stick figures OUTSIDE the boundary):
- LEFT SIDE: "Technician" (primary user), "Admin" (secondary user)
- RIGHT SIDE: "GroqAPI" (external service), "SerperAPI" (external service)
- BOTTOM RIGHT: "LeadsRepository" (database, draw as cylinder), "RecipesDB" (database, draw as cylinder)

USE CASES (draw as ovals INSIDE the boundary, organised in logical vertical groups):
GROUP 1 – Authentication (top left area):
  - "Register Account"
  - "Login"

GROUP 2 – Task Management (centre-left):
  - "Input Target URL or Document"
  - "Train Visual Selector"
  - "Start Extraction Task"
  - "Pause / Resume Task"

GROUP 3 – Monitoring & History (centre):
  - "Monitor Live Progress"
  - "View Past Extractions"
  - "Browse Leads by Industry"
  - "Export Leads"

GROUP 4 – Internal Processing (centre-right):
  - "Crawl Web Pages"
  - "Parse Document"
  - "Sanitise Extracted Data"
  - "Check Lead Uniqueness"
  - "Save Checkpoint"
  - "Recover Task"

GROUP 5 – External Calls (far right, near external actors):
  - "Predict Pagination"
  - "Repair Malformed Data"
  - "Search Web for URLs"
  - "Lookup Site Recipe"
  - "Save Site Recipe"

RELATIONSHIPS (all arrows must have labels and point correctly):
- Admin → "Register Account" (association line)
- Admin → "Login" (association line)
- Technician → "Login" (association line)
- Technician → "Input Target URL or Document" (association)
- Technician → "Train Visual Selector" (association)
- Technician → "Start Extraction Task" (association)
- Technician → "Pause / Resume Task" (association)
- Technician → "Monitor Live Progress" (association)
- Technician → "View Past Extractions" (association)
- Technician → "Browse Leads by Industry" (association)
- Technician → "Export Leads" (association)
- "Start Extraction Task" → "Lookup Site Recipe"  labelled <<include>>
- "Start Extraction Task" → "Crawl Web Pages"  labelled <<include>>
- "Start Extraction Task" → "Parse Document"  labelled <<include>>
- "Start Extraction Task" → "Save Checkpoint"  labelled <<include>>
- "Crawl Web Pages" → "Sanitise Extracted Data"  labelled <<include>>
- "Sanitise Extracted Data" → "Check Lead Uniqueness"  labelled <<include>>
- "Predict Pagination" → "Crawl Web Pages"  labelled <<extend>>
- "Repair Malformed Data" → "Sanitise Extracted Data"  labelled <<extend>>
- "Recover Task" → "Start Extraction Task"  labelled <<extend>>
- "Input Target URL or Document" → "Search Web for URLs"  labelled <<include>>
- "Train Visual Selector" → "Save Site Recipe"  labelled <<include>>
- "Export Leads" → "Browse Leads by Industry"  labelled <<include>>
- GroqAPI ← "Predict Pagination" (association)
- GroqAPI ← "Repair Malformed Data" (association)
- SerperAPI ← "Search Web for URLs" (association)
- LeadsRepository ← "Check Lead Uniqueness" (association)
- RecipesDB ← "Lookup Site Recipe" (association)
- RecipesDB ← "Save Site Recipe" (association)

STYLE: White background. Black and dark-grey text. Ovals with thin borders. Dashed arrows for <<include>> and <<extend>>. Solid lines for actor associations. Include <<include>> and <<extend>> labels on dashed lines. Clean, academic UML style. No colour fills. Well-spaced so no elements overlap.
```

---

## SECTION 3 — Class Diagram

### 3.1 Classes, Attributes & Methods

```
CLASS: Technician
  Attributes:
    - technicianId: String
    - name: String
    - email: String
  Methods:
    + inputTarget(urlOrPath: String): void
    + trainSelector(cssSelector: String): void
    + startTask(): void
    + pauseTask(): void
    + resumeTask(): void
    + exportLeads(format: String): void
    + viewHistory(): List<Task>
    + browseLeads(industry: String): List<Lead>

CLASS: Admin
  Attributes:
    - adminId: String
    - name: String
    - email: String
    - passwordHash: String
  Methods:
    + register(): void
    + login(email, password): Boolean
    + manageUsers(): void

CLASS: ExtractionCoordinator  [Central Controller]
  Attributes:
    - currentTaskId: Integer
    - status: String  {IDLE, SCANNING, EXTRACTING, PAUSED, COMPLETED}
    - targetInput: String
  Methods:
    + handleInput(input: String): void
    + startExtraction(): void
    + stopExtraction(): void
    + resumeFromCheckpoint(checkpointId: Integer): void
    + notifyStatus(message: String): void

CLASS: WebScraper
  Attributes:
    - threadPool: Integer
    - proxyList: List<String>
    - currentURL: String
  Methods:
    + fetchPage(url: String): String
    + execute(recipe: SiteRecipe): void
    + stop(): void

CLASS: DocumentParser
  Attributes:
    - documentPath: String
    - ocrBuffer: String
  Methods:
    + parse(filePath: String): String
    + stopOCR(): void

CLASS: DataSanitizer
  Attributes:
    - regexPatterns: Map<String, String>
  Methods:
    + stripPrefixes(text: String): String
    + repairEmail(email: String): String
    + formatPhone(number: String): String
    + clean(rawData: String): String
    + validate(lead: Lead): Boolean

CLASS: MLAdapter
  Attributes:
    - apiKey: String
    - modelVersion: String
  Methods:
    + predictPagination(html: String): String
    + repairAttribute(fragment: String): String

CLASS: StateManager
  Attributes:
    - checkpointInterval: Integer
    - lastCheckpointId: Integer
  Methods:
    + saveCheckpoint(task: Task): void
    + readCheckpoint(taskId: Integer): TaskCheckpoint
    + clearCheckpoint(taskId: Integer): void

CLASS: DatabaseManager
  Attributes:
    - sqliteConnection: String
    - cacheLimit: Integer
  Methods:
    + persistLead(lead: Lead): void
    + checkDuplicate(hash: String): Boolean
    + queryRecipe(domain: String): SiteRecipe
    + saveRecipe(recipe: SiteRecipe): void
    + getTaskHistory(): List<Task>

CLASS: ExportEngine
  Attributes:
    - outputPath: String
  Methods:
    + generateCSV(data: List<Lead>): File
    + generateXLSX(data: List<Lead>): File
    + generatePDF(data: List<Lead>): File
    + saveToLocal(file: File, path: String): void

CLASS: Lead  [Entity / Data Object]
  Attributes:
    + leadId: UUID
    + companyName: String
    + email: String
    + phone: String
    + industryTag: String
    + sourceUrl: String
    + extractionDate: DateTime
    + leadHash: String
  Methods:
    + toJSON(): String
    + validate(): Boolean

CLASS: SiteRecipe  [Entity / Data Object]
  Attributes:
    + recipeId: Integer
    + domainUrl: String
    + selectorsJSON: String
    + lastTrained: Date
    + successRate: Float
  Methods:
    + isValid(): Boolean
    + update(newSelectors: String): void

CLASS: TaskCheckpoint  [Entity / Data Object]
  Attributes:
    + taskId: Integer
    + lastUrl: String
    + recordIndex: Integer
    + status: String
    + recipeId: Integer
```

### 3.2 UML Relationships Between Classes

| Relationship | Type | From → To | Multiplicity | Note |
|---|---|---|---|---|
| Technician uses | Association | Technician → ExtractionCoordinator | 1 to 1 | Technician drives the coordinator |
| Admin manages | Association | Admin → Technician | 1 to many | Admin creates/manages technician accounts |
| Coordinator controls | Association | ExtractionCoordinator → WebScraper | 1 to 1 | Coordinator invokes scraper for web tasks |
| Coordinator controls | Association | ExtractionCoordinator → DocumentParser | 1 to 1 | Coordinator invokes parser for file tasks |
| Coordinator delegates | Association | ExtractionCoordinator → DataSanitizer | 1 to 1 | All raw data passes through sanitizer |
| Coordinator delegates | Association | ExtractionCoordinator → StateManager | 1 to 1 | Coordinator triggers checkpointing |
| Coordinator uses | Association | ExtractionCoordinator → DatabaseManager | 1 to 1 | Coordinator queries and persists via DB manager |
| Coordinator produces | Association | ExtractionCoordinator → ExportEngine | 1 to 1 | Coordinator triggers export on completion |
| Sanitizer calls | Dependency | DataSanitizer → MLAdapter | dashed arrow | Only when regex insufficient |
| WebScraper queries | Dependency | WebScraper → DatabaseManager | dashed arrow | Looks up site recipe before crawling |
| MLAdapter calls | Dependency | MLAdapter → GroqAPI | dashed arrow | External API call |
| WebScraper calls | Dependency | WebScraper → SerperAPI | dashed arrow | URL discovery calls |
| DatabaseManager manages | Association | DatabaseManager → Lead | 1 to many | Persists and retrieves leads |
| DatabaseManager manages | Association | DatabaseManager → SiteRecipe | 1 to many | Reads and writes site recipes |
| DatabaseManager manages | Association | DatabaseManager → TaskCheckpoint | 1 to many | Writes and reads checkpoints |
| StateManager writes | Dependency | StateManager → TaskCheckpoint | dashed arrow | Creates checkpoint objects |
| ExportEngine reads | Dependency | ExportEngine → Lead | dashed arrow | Pulls lead data for serialisation |
| WebScraper uses | Dependency | WebScraper → SiteRecipe | dashed arrow | Executes CSS selectors from recipe |
| DataSanitizer produces | Association | DataSanitizer → Lead | 1 to many | Outputs clean Lead objects |

### 3.3 Image Generation Prompt

```
Create a clean UML Class Diagram for a system called "Enolix Outreach System (EOS)".

Draw 12 classes as rectangles divided into three horizontal sections: class name (top, shaded), attributes (middle), methods (bottom). 

Use standard UML visibility symbols: + for public, - for private, # for protected.
Do NOT use colour fills. Use light grey shading only for the class name row.

CLASSES TO DRAW (layout them in a logical grid, left to right):

ROW 1 – Human Actors (top-left):
  Box 1: Admin
    Attributes: -adminId:String, -name:String, -email:String, -passwordHash:String
    Methods: +register():void, +login():Boolean, +manageUsers():void

  Box 2: Technician
    Attributes: -technicianId:String, -name:String, -email:String
    Methods: +inputTarget():void, +trainSelector():void, +startTask():void, +exportLeads():void, +viewHistory():List, +browseLeads():List

ROW 2 – Controllers / Agents (middle row, left to right):
  Box 3: ExtractionCoordinator
    Attributes: -currentTaskId:Integer, -status:String, -targetInput:String
    Methods: +handleInput():void, +startExtraction():void, +stopExtraction():void, +resumeFromCheckpoint():void

  Box 4: WebScraper
    Attributes: -threadPool:Integer, -currentURL:String
    Methods: +fetchPage():String, +execute():void, +stop():void

  Box 5: DocumentParser
    Attributes: -documentPath:String, -ocrBuffer:String
    Methods: +parse():String, +stopOCR():void

  Box 6: DataSanitizer
    Attributes: -regexPatterns:Map
    Methods: +stripPrefixes():String, +repairEmail():String, +formatPhone():String, +clean():String, +validate():Boolean

  Box 7: MLAdapter
    Attributes: -apiKey:String
    Methods: +predictPagination():String, +repairAttribute():String

  Box 8: StateManager
    Attributes: -checkpointInterval:Integer
    Methods: +saveCheckpoint():void, +readCheckpoint():Checkpoint, +clearCheckpoint():void

  Box 9: DatabaseManager
    Attributes: -sqliteConnection:String
    Methods: +persistLead():void, +checkDuplicate():Boolean, +queryRecipe():SiteRecipe, +saveRecipe():void, +getTaskHistory():List

  Box 10: ExportEngine
    Attributes: -outputPath:String
    Methods: +generateCSV():File, +generateXLSX():File, +generatePDF():File

ROW 3 – Data Entities (bottom row):
  Box 11: Lead
    Attributes: +leadId:UUID, +companyName:String, +email:String, +phone:String, +industryTag:String, +leadHash:String
    Methods: +toJSON():String, +validate():Boolean

  Box 12: SiteRecipe
    Attributes: +recipeId:Integer, +domainUrl:String, +selectorsJSON:String, +successRate:Float
    Methods: +isValid():Boolean, +update():void

  Box 13: TaskCheckpoint
    Attributes: +taskId:Integer, +lastUrl:String, +recordIndex:Integer, +status:String
    (no methods)

RELATIONSHIPS (draw all of these — this is critical):
- Admin → Technician: solid line with open arrowhead, labelled "manages", multiplicity 1 on Admin side, * on Technician side
- Technician → ExtractionCoordinator: solid association line, labelled "uses", 1 to 1
- ExtractionCoordinator → WebScraper: solid association line, labelled "invokes", 1 to 1
- ExtractionCoordinator → DocumentParser: solid association line, labelled "invokes", 1 to 1
- ExtractionCoordinator → DataSanitizer: solid association line, labelled "delegates to", 1 to 1
- ExtractionCoordinator → StateManager: solid association line, labelled "triggers", 1 to 1
- ExtractionCoordinator → DatabaseManager: solid association line, labelled "uses", 1 to 1
- ExtractionCoordinator → ExportEngine: solid association line, labelled "triggers", 1 to 1
- DataSanitizer → MLAdapter: dashed arrow (dependency), labelled "<<uses>>"
- WebScraper → DatabaseManager: dashed arrow (dependency), labelled "<<queries>>"
- WebScraper → SiteRecipe: dashed arrow, labelled "<<uses>>"
- DataSanitizer → Lead: solid arrow, labelled "produces", 1 to many
- DatabaseManager → Lead: solid line, labelled "manages", 1 to many
- DatabaseManager → SiteRecipe: solid line, labelled "manages", 1 to many
- DatabaseManager → TaskCheckpoint: solid line, labelled "manages", 1 to many
- StateManager → TaskCheckpoint: dashed arrow, labelled "<<writes>>"
- ExportEngine → Lead: dashed arrow, labelled "<<reads>>"

EXTERNAL ACTORS (draw as simple labelled boxes with a different border style, outside the main grid):
  - "GroqAPI" — connected to MLAdapter with dashed arrow labelled "<<calls>>"
  - "SerperAPI" — connected to WebScraper with dashed arrow labelled "<<calls>>"

STYLE: White background. All text in black. Grey shading only for class name rows. Standard UML solid and dashed arrows. No colour. Ensure no class is disconnected — every class must have at least one relationship line touching it. Academic, clean style.
```

---

## SECTION 4 — Activity Diagram

### 4.1 Swim Lanes
The activity diagram uses **5 swim lanes** aligned with the class diagram actors:

1. **Technician** — human actions (input, train, trigger, review)
2. **ExtractionCoordinator** — orchestration logic
3. **WebScraper / DocumentParser** — data retrieval (can be one combined lane)
4. **DataSanitizer / MLAdapter** — cleaning and ML repair
5. **DatabaseManager / StateManager** — persistence and checkpointing

### 4.2 Activity Flow Description

```
START → Technician: Login
→ Technician: Choose input type [Web URL | Document File | Company Name Prompt]

[If Company Name Prompt]
→ ExtractionCoordinator: Send query to SerperAPI → receive URL list → proceed as Web URL

[If Web URL]
→ ExtractionCoordinator: Query RecipesDB for existing Site Recipe
  → [Recipe Found] → Load recipe → Go to SCRAPE
  → [No Recipe] → Notify Technician → Technician: Train Visual Selector
      → ExtractionCoordinator: Save new SiteRecipe to RecipesDB → Go to SCRAPE

[If Document File]
→ ExtractionCoordinator: Send to DocumentParser → OCR → raw text → Go to SANITIZE

SCRAPE:
→ WebScraper: Fetch page HTML (multi-threaded)
  → [Pagination detected] → WebScraper: Check if pagination is complex
      → [Complex] → MLAdapter: Call GroqAPI → receive pagination pattern
      → [Simple] → Continue loop
  → WebScraper: Send raw HTML buffer to DataSanitizer
  → StateManager: Save checkpoint every N records

SANITIZE:
→ DataSanitizer: Apply regex — strip prefixes, repair emails, format phone numbers
  → [Data repaired successfully] → Produce Lead object → Go to DEDUPLICATE
  → [Data too malformed] → MLAdapter: Call GroqAPI for contextual repair → return repaired attributes → Go to DEDUPLICATE

DEDUPLICATE:
→ DatabaseManager: Generate SHA-256 hash for Lead
  → [Duplicate found] → Discard record → return to SCRAPE loop
  → [Unique] → DatabaseManager: Persist Lead to LeadsRepository

LOOP DECISION:
→ ExtractionCoordinator: More pages remaining?
  → [Yes] → Return to SCRAPE
  → [No] → Task status = COMPLETED

[At any point during SCRAPE or SANITIZE]
→ [User triggers PAUSE] → StateManager: Save checkpoint → ExtractionCoordinator: status = PAUSED → WAIT
→ [User triggers RESUME] → StateManager: Read checkpoint → ExtractionCoordinator: resume from last index

[At any point — system failure]
→ StateManager: Checkpoint already saved → ExtractionCoordinator: on restart, detect partial task → offer RECOVER
→ Technician: Choose Recover → StateManager: load checkpoint → resume

POST-TASK:
→ Technician: Browse LeadsRepository by industry
→ Technician: Select leads → ExportEngine: Generate file (CSV / XLSX / PDF)
→ ExportEngine: Save to LocalFileSystem
→ STOP
```

### 4.3 Image Generation Prompt

```
Create a clean UML Activity Diagram with swim lanes for a system called "Enolix Outreach System (EOS)".

Draw 5 vertical swim lanes with these exact labels at the top:
  Lane 1: "Technician"
  Lane 2: "ExtractionCoordinator"
  Lane 3: "WebScraper / DocumentParser"
  Lane 4: "DataSanitizer / MLAdapter"
  Lane 5: "DatabaseManager / StateManager"

Draw the following activities as rounded rectangles in the correct lane. Connect all activities with solid arrows pointing in the correct direction of flow. Use diamond shapes for all decision points.

ACTIVITIES IN ORDER (top to bottom):

Lane 1:  [START bullet] → activity "Login"
Lane 1:  → diamond "Input Type?" with three branches:
  Branch A label "Web URL" → Lane 2 activity "Query RecipesDB for Site Recipe"
  Branch B label "Document File" → Lane 3 activity "Send to DocumentParser"
  Branch C label "Company Prompt" → Lane 2 activity "Query SerperAPI for URLs" → merge to Branch A

Lane 2 (after Recipe query): diamond "Recipe Found?"
  → [Yes] → activity "Load SiteRecipe" → Lane 3 "Start WebScraper"
  → [No] → Lane 1 activity "Train Visual Selector" → Lane 2 activity "Save SiteRecipe to RecipesDB" → Lane 3 "Start WebScraper"

Lane 3: activity "Fetch Page HTML (multi-threaded)"
  → diamond "Pagination Complex?"
    → [Yes] → Lane 4 activity "MLAdapter: Predict Pagination via GroqAPI" → back to Lane 3 "Continue Fetch"
    → [No] → Lane 3 "Continue Fetch"
  → activity "Send raw HTML to DataSanitizer"

Lane 3 (Document branch): activity "DocumentParser: OCR Processing" → merge into Lane 4 "Sanitise Data"

Lane 4: activity "DataSanitizer: Apply Regex (strip, repair, format)"
  → diamond "Data Valid?"
    → [Yes] → activity "Produce Lead object"
    → [No] → activity "MLAdapter: Call GroqAPI for contextual repair" → activity "Produce Lead object"

Lane 5: activity "DatabaseManager: Generate SHA-256 Hash"
  → diamond "Duplicate?"
    → [Yes] → discard → arrow back up to Lane 3 "Fetch Page HTML" (loop)
    → [No] → activity "Persist Lead to LeadsRepository"

Lane 5: activity "StateManager: Save Checkpoint (every N records)"
  [This checkpoint activity connects back from the persist step with a side arrow]

Lane 2: diamond "More Pages?"
  → [Yes] → arrow back up to Lane 3 "Fetch Page HTML" (loop arrow on the left side)
  → [No] → activity "Task status = COMPLETED"

PARALLEL EXCEPTION FLOW (show as a separate dashed side path):
  From anywhere in Lane 3 or 4: diamond "User Paused?"
    → [Yes] → Lane 5 "StateManager: Save Checkpoint" → Lane 1 "Status = PAUSED — await resume"
    → On Resume → Lane 5 "StateManager: Read Checkpoint" → Lane 2 "Resume from saved index"

Lane 1 (POST-TASK): activity "Browse Leads by Industry"
  → activity "Select leads for export"
  → Lane 4 / Lane 5 area: activity "ExportEngine: Generate CSV / XLSX / PDF"
  → activity "Save to Local File System"
  → [END bullet]

STYLE: White background. Black text. Light grey swim lane headers. All arrows black with arrowheads. Diamond decision shapes clearly labelled. Rounded rectangles for activities. Filled black circle for START, bullseye circle for END. No colour fills. Clean, academic UML layout.
```

---

## SECTION 5 — Sequence Diagram

### 5.1 Lifelines (Participants)
Draw these as vertical dashed lifelines in this left-to-right order:

1. `Technician`
2. `ExtractionCoordinator`
3. `DatabaseManager`
4. `WebScraper`
5. `DataSanitizer`
6. `MLAdapter`
7. `StateManager`
8. `GroqAPI`
9. `LeadsRepository`

### 5.2 Message Sequence

```
1. Technician → ExtractionCoordinator: startTask(url)
2. ExtractionCoordinator → DatabaseManager: queryRecipe(domain)
3. DatabaseManager → ExtractionCoordinator: return SiteRecipe (or null)

   [alt — no recipe found]
   4a. ExtractionCoordinator → Technician: requestTraining()
   4b. Technician → ExtractionCoordinator: submitSelector(cssSelector)
   4c. ExtractionCoordinator → DatabaseManager: saveRecipe(SiteRecipe)

5. ExtractionCoordinator → WebScraper: execute(SiteRecipe)

LOOP — for each page:
6. WebScraper → TargetSite: fetchPage(url) [note: TargetSite is external, shown as boundary box]
7. WebScraper → WebScraper: raw_HTML_buffer [self-message / processing note]

   [opt — if pagination is complex]
   8a. WebScraper → MLAdapter: predictPagination(html)
   8b. MLAdapter → GroqAPI: POST /predict {html_fragment}
   8c. GroqAPI → MLAdapter: return paginationPattern
   8d. MLAdapter → WebScraper: return paginationPattern

9. WebScraper → DataSanitizer: clean(rawData)
10. DataSanitizer → DataSanitizer: applyRegex() [self-message]

    [opt — if data too malformed]
    11a. DataSanitizer → MLAdapter: repairAttribute(fragment)
    11b. MLAdapter → GroqAPI: POST /repair {fragment}
    11c. GroqAPI → MLAdapter: return repairedData
    11d. MLAdapter → DataSanitizer: return repairedData

12. DataSanitizer → ExtractionCoordinator: return Lead(sanitisedData)
13. ExtractionCoordinator → DatabaseManager: checkDuplicate(leadHash)
14. DatabaseManager → LeadsRepository: SELECT WHERE hash = leadHash
15. LeadsRepository → DatabaseManager: return isDuplicate

    [alt — if NOT duplicate]
    16a. DatabaseManager → LeadsRepository: INSERT lead
    16b. LeadsRepository → DatabaseManager: confirm persisted

    [alt — if DUPLICATE]
    16c. DatabaseManager → ExtractionCoordinator: discard (duplicate)

17. ExtractionCoordinator → StateManager: saveCheckpoint(taskId, currentIndex, currentURL)
18. StateManager → DatabaseManager: writeCheckpoint(TaskCheckpoint)

END LOOP

19. ExtractionCoordinator → Technician: notifyCompletion(taskSummary)
20. Technician → ExtractionCoordinator: requestExport(format)
21. ExtractionCoordinator → ExportEngine: generateFile(leads, format) [ExportEngine shown as separate activation box on DatabaseManager lifeline or separate lifeline]
22. ExportEngine → Technician: return exportedFile

RECOVERY SEQUENCE (show as a separate combined fragment at the bottom, labelled "ref: Task Recovery"):
A. Technician → ExtractionCoordinator: restartTask()
B. ExtractionCoordinator → StateManager: readCheckpoint(taskId)
C. StateManager → DatabaseManager: SELECT checkpoint WHERE taskId
D. DatabaseManager → StateManager: return TaskCheckpoint
E. StateManager → ExtractionCoordinator: return resumeIndex + lastURL
F. ExtractionCoordinator → WebScraper: execute(recipe, startFrom=resumeIndex)
```

### 5.3 Image Generation Prompt

```
Create a clean UML Sequence Diagram for a system called "Enolix Outreach System (EOS)".

Draw 9 participants as labelled boxes at the top with vertical dashed lifelines extending downward, in this exact left-to-right order:
  1. Technician
  2. ExtractionCoordinator
  3. DatabaseManager
  4. WebScraper
  5. DataSanitizer
  6. MLAdapter
  7. StateManager
  8. GroqAPI
  9. LeadsRepository

Show activation bars (thin rectangles on lifelines) when a participant is active.

MESSAGES (draw as horizontal arrows, solid for calls, dashed for returns, in this order top to bottom):

1. Technician → ExtractionCoordinator: solid arrow, label "startTask(url)"
2. ExtractionCoordinator → DatabaseManager: solid arrow, label "queryRecipe(domain)"
3. DatabaseManager → ExtractionCoordinator: dashed return arrow, label "SiteRecipe | null"

[Combined fragment box labelled "alt — Recipe Not Found"]:
4a. ExtractionCoordinator → Technician: solid arrow, label "requestTraining()"
4b. Technician → ExtractionCoordinator: solid arrow, label "submitSelector(css)"
4c. ExtractionCoordinator → DatabaseManager: solid arrow, label "saveRecipe(SiteRecipe)"

5. ExtractionCoordinator → WebScraper: solid arrow, label "execute(SiteRecipe)"

[Loop fragment box labelled "loop — for each page"]:
6. WebScraper → WebScraper: self-arrow, label "fetchPage(url) / buffer HTML"

[opt fragment box labelled "opt — Complex Pagination"]:
7a. WebScraper → MLAdapter: solid arrow, label "predictPagination(html)"
7b. MLAdapter → GroqAPI: solid arrow, label "POST /predict"
7c. GroqAPI → MLAdapter: dashed arrow, label "paginationPattern"
7d. MLAdapter → WebScraper: dashed arrow, label "paginationPattern"

8. WebScraper → DataSanitizer: solid arrow, label "clean(rawData)"
9. DataSanitizer → DataSanitizer: self-arrow, label "applyRegex()"

[opt fragment box labelled "opt — Data Malformed"]:
10a. DataSanitizer → MLAdapter: solid arrow, label "repairAttribute(fragment)"
10b. MLAdapter → GroqAPI: solid arrow, label "POST /repair"
10c. GroqAPI → MLAdapter: dashed arrow, label "repairedData"
10d. MLAdapter → DataSanitizer: dashed arrow, label "repairedData"

11. DataSanitizer → ExtractionCoordinator: dashed return arrow, label "Lead(sanitisedData)"
12. ExtractionCoordinator → DatabaseManager: solid arrow, label "checkDuplicate(hash)"
13. DatabaseManager → LeadsRepository: solid arrow, label "SELECT WHERE hash"
14. LeadsRepository → DatabaseManager: dashed arrow, label "isDuplicate: Boolean"

[alt fragment — "alt — Unique | Duplicate"]:
  [Unique branch]: DatabaseManager → LeadsRepository: solid arrow, label "INSERT lead"
                   LeadsRepository → DatabaseManager: dashed arrow, label "confirmed"
  [Duplicate branch]: DatabaseManager → ExtractionCoordinator: dashed arrow, label "discard"

15. ExtractionCoordinator → StateManager: solid arrow, label "saveCheckpoint(taskId, index, url)"
16. StateManager → DatabaseManager: solid arrow, label "writeCheckpoint()"

[End loop]

17. ExtractionCoordinator → Technician: solid arrow, label "notifyCompletion(summary)"
18. Technician → ExtractionCoordinator: solid arrow, label "requestExport(format)"
19. ExtractionCoordinator → Technician: dashed arrow, label "exportedFile"

[Reference frame at bottom labelled "ref — Task Recovery"]:
A. Technician → ExtractionCoordinator: solid arrow, label "restartTask()"
B. ExtractionCoordinator → StateManager: solid arrow, label "readCheckpoint(taskId)"
C. StateManager → DatabaseManager: solid arrow, label "SELECT checkpoint"
D. DatabaseManager → StateManager: dashed arrow, label "TaskCheckpoint"
E. StateManager → ExtractionCoordinator: dashed arrow, label "resumeIndex + lastURL"
F. ExtractionCoordinator → WebScraper: solid arrow, label "execute(recipe, from=resumeIndex)"

STYLE: White background. Black text and arrows. Thin vertical dashed lifelines. Solid horizontal arrows for method calls, dashed for return values. Fragment boxes with labels inside a top-left corner label. Activation bars shown as thin white rectangles on lifelines. Clean academic UML style. No colour. All labels visible and not overlapping.
```

---

## SECTION 6 — Database Design & ERD

### 6.1 Why the Current Design Is Shallow
The original design had 3 tables. The system's actual requirements — user auth (data protection), industry browsing, task recovery, export history, and adaptive memory — demand a broader schema. The expanded design below adds: `users`, `tasks`, `export_logs`, and splits the lead record properly.

### 6.2 Full Table Definitions

---

#### TABLE: `users`
*Stores all system users (Admin + Technician) for authentication and access control.*

| Column | Type | Constraints | Description |
|---|---|---|---|
| user_id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique user identifier |
| name | VARCHAR(100) | NOT NULL | Full name |
| email | VARCHAR(150) | UNIQUE, NOT NULL | Login email |
| password_hash | VARCHAR(255) | NOT NULL | Bcrypt hash of password |
| role | VARCHAR(20) | NOT NULL DEFAULT 'technician' | 'admin' or 'technician' |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | Account creation date |
| is_active | BOOLEAN | DEFAULT TRUE | Soft-delete / deactivation flag |

---

#### TABLE: `tasks`
*Tracks every extraction task started by a technician.*

| Column | Type | Constraints | Description |
|---|---|---|---|
| task_id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique task identifier |
| user_id | INTEGER | FK → users.user_id | Who initiated the task |
| input_value | TEXT | NOT NULL | The URL, file path, or prompt entered |
| input_type | VARCHAR(20) | NOT NULL | 'url', 'document', or 'prompt' |
| status | VARCHAR(20) | DEFAULT 'idle' | 'idle', 'scanning', 'extracting', 'paused', 'completed', 'failed' |
| total_leads | INTEGER | DEFAULT 0 | Count of leads collected |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | Task start time |
| completed_at | TIMESTAMP | NULLABLE | Task end time |
| recipe_id | INTEGER | FK → site_recipes.recipe_id | Which recipe was used (if web task) |

---

#### TABLE: `site_recipes`
*Adaptive memory — stores learned CSS selectors and pagination patterns per domain.*

| Column | Type | Constraints | Description |
|---|---|---|---|
| recipe_id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique recipe identifier |
| domain_url | VARCHAR(255) | UNIQUE, NOT NULL, INDEXED | Base domain the recipe applies to |
| selectors_json | TEXT | NOT NULL | JSON blob of CSS/regex selectors |
| pagination_pattern | VARCHAR(255) | NULLABLE | Pagination CSS or URL pattern |
| last_trained | DATE | NULLABLE | Last update by Technician or ML |
| success_rate | REAL | DEFAULT 0.0 | Ratio of valid leads per use |
| trained_by_user_id | INTEGER | FK → users.user_id | Who trained this recipe |

---

#### TABLE: `task_checkpoints`
*State persistence — enables task recovery after crash or pause.*

| Column | Type | Constraints | Description |
|---|---|---|---|
| checkpoint_id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique checkpoint identifier |
| task_id | INTEGER | FK → tasks.task_id, UNIQUE | One active checkpoint per task |
| last_url | TEXT | NULLABLE | Last URL successfully fetched |
| record_index | INTEGER | DEFAULT 0 | Index of last lead saved |
| status | VARCHAR(20) | DEFAULT 'in-progress' | 'in-progress', 'paused', 'failed' |
| saved_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | When checkpoint was written |

---

#### TABLE: `leads_repository`
*The global store of all extracted, deduplicated, sanitised leads.*

| Column | Type | Constraints | Description |
|---|---|---|---|
| lead_id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique lead identifier |
| task_id | INTEGER | FK → tasks.task_id | Which task produced this lead |
| company_name | VARCHAR(255) | NOT NULL | Name of the business |
| email | VARCHAR(150) | NULLABLE | Sanitised business email |
| phone_number | VARCHAR(30) | NULLABLE | Standardised phone (+254 format) |
| source_url | TEXT | NULLABLE | URL the lead was extracted from |
| industry_tag | VARCHAR(100) | INDEXED | Industry category label |
| region | VARCHAR(100) | NULLABLE | Geographic region if available |
| lead_hash | VARCHAR(64) | UNIQUE, NOT NULL | SHA-256 of email+company to prevent duplicates |
| extraction_date | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | When record was persisted |
| recipe_id | INTEGER | FK → site_recipes.recipe_id | Which recipe produced this lead |

---

#### TABLE: `export_logs`
*Records every export action for audit and traceability.*

| Column | Type | Constraints | Description |
|---|---|---|---|
| export_id | INTEGER | PRIMARY KEY, AUTOINCREMENT | Unique export identifier |
| user_id | INTEGER | FK → users.user_id | Who triggered the export |
| task_id | INTEGER | FK → tasks.task_id, NULLABLE | Which task's leads were exported |
| format | VARCHAR(10) | NOT NULL | 'csv', 'xlsx', or 'pdf' |
| record_count | INTEGER | DEFAULT 0 | Number of leads in the export |
| filters_json | TEXT | NULLABLE | JSON of industry/region filters applied |
| exported_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | When export was generated |

---

### 6.3 Table Relationships Summary

| Relationship | From Table → To Table | Type | FK Column |
|---|---|---|---|
| User initiates tasks | users → tasks | One-to-Many | tasks.user_id |
| Task uses recipe | tasks → site_recipes | Many-to-One | tasks.recipe_id |
| Task has one checkpoint | tasks → task_checkpoints | One-to-One | task_checkpoints.task_id |
| Task produces leads | tasks → leads_repository | One-to-Many | leads_repository.task_id |
| Lead came from recipe | leads_repository → site_recipes | Many-to-One | leads_repository.recipe_id |
| User trains recipes | users → site_recipes | One-to-Many | site_recipes.trained_by_user_id |
| User creates exports | users → export_logs | One-to-Many | export_logs.user_id |
| Export covers task | tasks → export_logs | One-to-Many | export_logs.task_id |

### 6.4 ERD Image Generation Prompt

```
Create a clean UML Entity-Relationship Diagram (ERD) for a database called "Enolix Outreach System (EOS)".

Use Crow's Foot notation for all relationships (lines with crow's foot symbols at the "many" end and a single vertical line at the "one" end).

Draw 6 entity tables as rectangles. Each entity has three columns inside: column name, data type, and constraints.

Mark PRIMARY KEY fields with "PK" on the left. Mark FOREIGN KEY fields with "FK" on the left. Underline primary key field names.

ENTITIES (draw as labelled rectangles with column rows):

TABLE 1: users
  PK  user_id: INTEGER — PRIMARY KEY AUTOINCREMENT
      name: VARCHAR(100) — NOT NULL
      email: VARCHAR(150) — UNIQUE NOT NULL
      password_hash: VARCHAR(255) — NOT NULL
      role: VARCHAR(20) — DEFAULT 'technician'
      is_active: BOOLEAN — DEFAULT TRUE
      created_at: TIMESTAMP

TABLE 2: tasks
  PK  task_id: INTEGER — PRIMARY KEY AUTOINCREMENT
  FK  user_id: INTEGER — FK → users
      input_value: TEXT — NOT NULL
      input_type: VARCHAR(20)
      status: VARCHAR(20)
      total_leads: INTEGER
      created_at: TIMESTAMP
      completed_at: TIMESTAMP
  FK  recipe_id: INTEGER — FK → site_recipes

TABLE 3: site_recipes
  PK  recipe_id: INTEGER — PRIMARY KEY AUTOINCREMENT
      domain_url: VARCHAR(255) — UNIQUE INDEXED
      selectors_json: TEXT — NOT NULL
      pagination_pattern: VARCHAR(255)
      last_trained: DATE
      success_rate: REAL
  FK  trained_by_user_id: INTEGER — FK → users

TABLE 4: task_checkpoints
  PK  checkpoint_id: INTEGER — PRIMARY KEY AUTOINCREMENT
  FK  task_id: INTEGER — FK → tasks (UNIQUE)
      last_url: TEXT
      record_index: INTEGER
      status: VARCHAR(20)
      saved_at: TIMESTAMP

TABLE 5: leads_repository
  PK  lead_id: INTEGER — PRIMARY KEY AUTOINCREMENT
  FK  task_id: INTEGER — FK → tasks
      company_name: VARCHAR(255) — NOT NULL
      email: VARCHAR(150)
      phone_number: VARCHAR(30)
      source_url: TEXT
      industry_tag: VARCHAR(100) — INDEXED
      region: VARCHAR(100)
      lead_hash: VARCHAR(64) — UNIQUE NOT NULL
      extraction_date: TIMESTAMP
  FK  recipe_id: INTEGER — FK → site_recipes

TABLE 6: export_logs
  PK  export_id: INTEGER — PRIMARY KEY AUTOINCREMENT
  FK  user_id: INTEGER — FK → users
  FK  task_id: INTEGER — FK → tasks
      format: VARCHAR(10) — NOT NULL
      record_count: INTEGER
      filters_json: TEXT
      exported_at: TIMESTAMP

LAYOUT (arrange in a logical spatial flow):
  - users: top-left
  - site_recipes: top-centre
  - tasks: centre
  - task_checkpoints: centre-right (directly connected to tasks)
  - leads_repository: bottom-centre
  - export_logs: bottom-right

RELATIONSHIPS (draw Crow's Foot lines between tables):
- users to tasks: one (users) to many (tasks) — labelled "initiates"
- users to site_recipes: one (users) to many (site_recipes) — labelled "trains"
- users to export_logs: one (users) to many (export_logs) — labelled "creates"
- tasks to task_checkpoints: one (tasks) to one (task_checkpoints) — labelled "checkpointed by"
- tasks to leads_repository: one (tasks) to many (leads_repository) — labelled "produces"
- tasks to export_logs: one (tasks) to many (export_logs) — labelled "exported via"
- site_recipes to tasks: one (site_recipes) to many (tasks) — labelled "used by"
- site_recipes to leads_repository: one (site_recipes) to many (leads_repository) — labelled "sourced by"

STYLE: White background. Black text. Light grey header row for each table (with table name in bold). PK fields in bold. FK fields in italic. Crow's Foot notation at all "many" ends. Thin solid lines for relationships. Relationship labels on the connecting lines. No colour fills. Academic database ERD style.
```

---

## QUICK REFERENCE — Naming Cheat Sheet

| Old/Inconsistent Name | Correct Canonical Name |
|---|---|
| User, Operator, Staff | **Technician** |
| ML Subsystem, Groq Agent, AI Agent | **MLAdapter** (for the class) / **GroqAPI** (for the external service) |
| Web Agent, Serper Agent | **WebScraper** (class) / **SerperAPI** (external) |
| OCR System, OCR Engine | **DocumentParser** |
| DB Manager, Persistence Layer | **DatabaseManager** |
| Global Leads Repository, D2 | **LeadsRepository** |
| Recipe Data Store, D1, Adaptive Memory | **RecipesDB** / **site_recipes** (table) |
| Outreach System, EOS, the system | **ExtractionCoordinator** (when referring to the orchestrating class) |
| Self-Healing Agent | **DataSanitizer** |
| State Manager, Checkpoint Manager | **StateManager** |