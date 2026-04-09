# STUDS Functional Specification

Exhaustive checklist of every user-facing feature and observable behavior.

---

## Auth

### Landing Page (`/`)
- [ ] Displays STUDS logo with "(CONFIDENTIAL)" label
- [ ] Shows two portal buttons: STUDIO (lime) and HQ (lavender)
- [ ] STUDIO button navigates to `/studio/login`
- [ ] HQ button navigates to `/hq/login`

### Studio Login (`/studio/login`)
- [ ] Displays username and password fields
- [ ] Username field is autofocused
- [ ] Submitting valid store credentials logs in and redirects to `/studio/`
- [ ] Submitting the admin shortcut credentials (hq/hq) logs in as admin, bypasses lockout
- [ ] Submitting invalid credentials shows "Incorrect username or password." flash message
- [ ] Submitting valid credentials for a store whose timezone is Friday-Sunday shows lockout message: "Sorry, stud! The new SKU list will be available Monday."
- [ ] Lockout check is timezone-aware per store (Friday 00:00 through Sunday 23:59 in the store's local timezone)
- [ ] Lockout can be disabled via `feature_studio_lockout` setting in settings.json
- [ ] Back link navigates to landing page

### HQ Login (`/hq/login`)
- [ ] Displays username and password fields
- [ ] Username field is autofocused
- [ ] Submitting the admin shortcut credentials (hq/hq) logs in and redirects to `/hq/`
- [ ] Submitting valid hq_users credentials logs in with display name shown in header
- [ ] Submitting invalid credentials shows "Incorrect username or password." flash message
- [ ] Back link navigates to landing page
- [ ] "(CONFIDENTIAL)" label displayed

### Session & Logout
- [ ] Studio logout (`/studio/logout`) clears studio session and redirects to landing page
- [ ] HQ logout (`/hq/logout`) clears HQ session and redirects to landing page
- [ ] Accessing any `/studio/` route without session redirects to studio login
- [ ] Accessing any `/hq/` route without session redirects to HQ login

### Portal Switching
- [ ] HQ header contains STUDIO link that navigates to `/hq/goto-studio`, which sets studio session and redirects to `/studio/`
- [ ] Admin users in Studio portal see an HQ link that navigates to `/studio/goto-hq`, which sets HQ session and redirects to `/hq/`

---

## HQ Dashboard (`/hq/?section=dashboard`)

### SPA Shell (applies to all HQ sections)
- [ ] Header displays STUDS logo with "(CONFIDENTIAL)" label
- [ ] Left nav box (lime): HQ (current/bold) | STUDIO | LOGOUT
- [ ] Right nav box (lavender): FILES | REFRESH | SETTINGS
- [ ] User display name shown below header (if logged in as named user)
- [ ] "UPDATED:" timestamp shown below header, updates on refresh
- [ ] Section nav bar: DASHBOARD | ANALYTICS | DATABASE | STUDIOS
- [ ] Clicking a section link loads its content via AJAX into the main area without full page reload
- [ ] Active section link is visually highlighted
- [ ] Browser back/forward buttons navigate between sections via history.pushState
- [ ] Direct URL access with `?section=` parameter loads the correct section on page load
- [ ] Page scrolls to top when switching sections

### Summary Bar
- [ ] Displays Total Studios count
- [ ] Displays Updated count (green)
- [ ] Displays Discrepancy count (red)
- [ ] Displays Incomplete count (gray)
- [ ] Displays current SKU list filename (or dash if none)
- [ ] Displays SKU count from the loaded list (or dash if none)
- [ ] Displays audit trail date range as "min -> max" (or dash if no audit trail)

### Bypass Banner
- [ ] If no SKU list file is present, a warning banner appears: "No SKU list loaded -- reconciling all variance SKUs..."
- [ ] In bypass mode, all variance SKUs are treated as active (no intersection filter)

### Warnings
- [ ] Warnings are displayed in a yellow/orange banner area below the summary bar
- [ ] Warning if multiple SKU lists found (uses most recent by date in filename)
- [ ] Warning if multiple audit trails found (uses most recent by date in filename)
- [ ] Warning if a variance file fails to parse

### Filter & Sort Controls
- [ ] Filter dropdown: All / Updated / Discrepancy Detected / Incomplete
- [ ] Selecting a filter hides non-matching store rows
- [ ] Incomplete filter matches both "Incomplete (missing file)" and "Incomplete (unrecognized file format)"
- [ ] Sort dropdown: Store ID / Status / Discrepancy Count
- [ ] Store ID sorts numerically ascending
- [ ] Status sorts: Discrepancy Detected first, then Incomplete, then Updated
- [ ] Discrepancy Count sorts descending (highest first)

### Action Links
- [ ] EXPORT CSV link downloads a CSV file of all reconciliation data
- [ ] ARCHIVE link navigates to the archive browser page

### Store Table
- [ ] One row per store (all 40 seeded stores always shown, plus any extra variance files)
- [ ] Columns: expand arrow | Studio name | Status badge | Assigned SKUs | Discrepancies | Net Discrepancy
- [ ] Status badge colors: Updated (green), Discrepancy Detected (red), Incomplete (gray)
- [ ] Stores with no variance file show "Incomplete (missing file)"
- [ ] Stores with unrecognized variance file schema show "Incomplete (unrecognized file format)"
- [ ] Clicking a store row or its arrow expands/collapses the detail row
- [ ] Expand arrow rotates from right-pointing to down-pointing when expanded
- [ ] Column headers are clickable to sort: Studio (string), Status (string), Assigned SKUs (number), Discrepancies (number), Net Discrepancy (number)
- [ ] Sort indicator arrow (up/down) appears on the active sort column
- [ ] Clicking the same column header toggles between ascending and descending

### Store Detail Row (Expanded)
- [ ] Shows a sub-table of SKU-level details
- [ ] Detail columns: SKU | Product ID | Required Push | Location | Item Cost Price | Actual Push | Discrepancy
- [ ] Non-zero discrepancy values are visually highlighted
- [ ] If status is "Discrepancy Detected", a GENERATE EMAIL button appears
- [ ] If status is "Updated" with no discrepancies, shows "No discrepancies -- all SKUs matched."

### Email Draft Modal
- [ ] Clicking GENERATE EMAIL fetches draft from `/hq/email-draft/<store_id>` via AJAX
- [ ] Modal displays: title "Email Draft -- [Store Name]", To field (editable), Subject field (readonly), Body field (readonly textarea)
- [ ] To field is pre-populated with the store email from settings (if configured)
- [ ] Subject format: "[Store Name] -- Stock Check Discrepancy"
- [ ] Body includes greeting, discrepancy explanation, SKU-by-SKU list, and sign-off
- [ ] Each SKU line shows: SKU, Required Adjustment, Actual Adjustment, Discrepancy
- [ ] COPY TO CLIPBOARD button copies "To: ... Subject: ... Body: ..." to clipboard
- [ ] After copying, button text changes to "Copied!" for 2 seconds then reverts
- [ ] Close button (X) closes the modal
- [ ] Clicking outside the modal content closes it

### Refresh
- [ ] REFRESH button in header sends POST to `/hq/refresh`
- [ ] On success, updates the "UPDATED:" timestamp in the header
- [ ] If currently on dashboard section, reloads the dashboard content
- [ ] On failure, shows an alert with the error

### Export CSV (`/hq/export`)
- [ ] Downloads a CSV file named `STUDS_Dashboard_Export_YYYYMMDD_HHMMSS.csv`
- [ ] CSV columns: Store ID, Store Name, Status, SKU, Product ID, Required Push, Location, Item Cost Price, Actual Push, Discrepancy
- [ ] Includes all SKU detail rows for stores that have variance data
- [ ] Stores without data get a single row with empty SKU fields

---

## HQ Analytics (`/hq/?section=analytics`)

### Sub-Navigation
- [ ] Sticky sub-nav bar with links: OVERVIEW | COMPLIANCE TREND | STORE RANKINGS | DISCREPANCY SKUS | DISTRIBUTION | STORE GROUPS
- [ ] Sub-nav becomes fixed to top of viewport when scrolled past its natural position (JS-based sticky since CSS sticky doesn't work in SPA content div)
- [ ] Clicking a sub-nav link smooth-scrolls to the corresponding panel
- [ ] Scroll offset accounts for the fixed header height and sub-nav height

### Network Summary Panel (OVERVIEW)
- [ ] Displays Network Compliance rate as a percentage
- [ ] Displays Average Update Lag in hours
- [ ] Displays Total Discrepancy Units
- [ ] Displays Chronic Offenders count (compliance < 60%) in red, clickable to scroll to Store Groups
- [ ] Displays Top Performers count (compliance >= 90%) in green, clickable to scroll to Store Groups

### 12-Week Compliance Trend (COMPLIANCE TREND)
- [ ] Stacked bar chart (Chart.js)
- [ ] X-axis: 12 week labels
- [ ] Y-axis: count, max 40
- [ ] Three datasets: Updated (lime), Discrepancy (red), Incomplete (gray)
- [ ] No animation
- [ ] Legend at bottom

### Studio Compliance Leaderboard (STORE RANKINGS)
- [ ] Sortable table with columns: Rank | Studio | Compliance Rate | Avg Lag | Discrepancy Units | Trend
- [ ] Top 5 rows visually highlighted (green/top style)
- [ ] Bottom 5 rows visually highlighted (red/bottom style)
- [ ] Trend column shows: up arrow + "Improving" (green), down arrow + "Declining" (red), right arrow + "Stable" (gray)
- [ ] All columns except Trend are sortable by clicking headers

### Chronic Discrepancy SKUs (DISCREPANCY SKUS)
- [ ] Sortable table with columns: SKU | Description | Total Units | Studios Affected | Weeks Appearing
- [ ] All columns are sortable by clicking headers

### Discrepancy Size Distribution (DISTRIBUTION)
- [ ] Bar chart (Chart.js)
- [ ] X-axis: discrepancy size buckets
- [ ] Y-axis: store-weeks count
- [ ] Lavender bar color
- [ ] No legend

### Studio Groups (STORE GROUPS)
- [ ] Two-column layout side by side
- [ ] Left: Chronic Offenders (compliance < 60%) with red heading
- [ ] Right: Top Performers (compliance >= 90%) with green heading
- [ ] Each group shows a table: Studio | Compliance Rate | Trend (arrow only)

---

## HQ Studios (`/hq/?section=studios`)

### Search
- [ ] Search input at top, autofocused on section load
- [ ] Typing filters the studios table in real-time by store name or number
- [ ] If 1-5 matches remain, a dropdown appears below the search input showing matching studios
- [ ] Clicking a dropdown item opens that studio's profile
- [ ] Dropdown hides when query has 0 matches or more than 5

### Studios Table
- [ ] Table with columns: Count (status dot) | Studio | Manager | Email | Phone
- [ ] Status dot colors: green (Updated), red (Discrepancy Detected), gray (Incomplete), hollow/unknown (no data)
- [ ] Studio and Manager columns are sortable by clicking headers
- [ ] Email and Phone columns are sortable by clicking headers
- [ ] Empty fields show dash (---)
- [ ] Clicking a row opens that studio's profile panel

### Studio Profile Panel
- [ ] Appears above the table when a studio is selected
- [ ] Header shows studio name + status dot + EDIT button
- [ ] Left column displays: Count Status (dot + text), Assigned SKUs, Discrepancies, Net Discrepancy
- [ ] Right column displays: Local Time (in store's timezone), Manager, Email, Phone
- [ ] Local time updates every 60 seconds while profile is open

### Studio Analytics (within profile)
- [ ] Compliance Rate percentage
- [ ] Average Update Lag in hours
- [ ] Total Discrepancy Units
- [ ] 12-week sparkline bar chart: lime bars for 0 discrepancies, red bars for >0
- [ ] Frequently Discrepant SKUs table (if any): SKU | Description | Occurrences
- [ ] "No analytics data available." shown if no data exists

### Edit Mode
- [ ] Clicking EDIT switches the profile to edit mode
- [ ] Manager, Email, Phone fields become editable text inputs
- [ ] Authentication section appears with: Username, New Password, Confirm Password fields
- [ ] SAVE and CANCEL buttons replace the EDIT button
- [ ] A save status message area appears next to the buttons
- [ ] Clicking CANCEL exits edit mode and re-renders the view profile
- [ ] Clicking SAVE posts to `/hq/studios/update-store` with JSON payload
- [ ] If passwords don't match, server returns error message displayed in status area
- [ ] On success, status shows "Saved." in green, then auto-returns to view mode after 800ms
- [ ] On error, status shows the error message in red
- [ ] On network failure, status shows "Network error" in red
- [ ] Saved data updates the local in-memory store data (no full page reload needed)

---

## HQ Files (`/hq/upload`)

### Header
- [ ] Same header layout as SPA shell
- [ ] FILES link shows as current/active
- [ ] REFRESH link reloads the page
- [ ] Section nav links (DASHBOARD, ANALYTICS, DATABASE, STUDIOS) navigate to the SPA

### Flash Messages
- [ ] Success messages displayed in green-styled banner
- [ ] Error messages displayed in standard warning banner

### Upload Section
- [ ] File input accepting `.csv` files, supports multiple file selection
- [ ] UPLOAD button submits the form
- [ ] RETURN TO DASHBOARD link navigates back to `/hq/`
- [ ] On successful upload, flash message shows count and filenames of uploaded files
- [ ] Recognized files (SKU list, variance, audit trail) are classified automatically by filename pattern
- [ ] If a file of the same name/type already exists, the old version is archived before overwriting

### File Table
- [ ] Only shown if files exist in `/input/`
- [ ] If no files exist, shows "No files found in /input/."
- [ ] Global files (SKU list, audit trail, other) listed first
- [ ] Variance files listed after a horizontal separator line
- [ ] Columns: File Name | Last Modified | Size | Actions
- [ ] File Name, Last Modified, and Size columns are sortable by clicking headers

### File Filtering
- [ ] Filter dropdown: All / SKU List / Audit Trail / Variance
- [ ] Selecting a filter shows only files of that type

### File Sorting
- [ ] Sort dropdown: Name A-Z / Name Z-A / Date Newest / Date Oldest / Size Largest / Size Smallest
- [ ] Selecting a sort option reorders the file rows accordingly

### File Actions (per row)
- [ ] DOWNLOAD link downloads the individual file
- [ ] DELETE button deletes the file after a browser confirmation dialog ("Delete [filename]?")
- [ ] Path traversal is blocked (filenames with `/` or `..` are rejected)

### Bulk Operations
- [ ] SELECT FILES button toggles checkbox visibility on each file row
- [ ] In select mode, button text changes to "CANCEL SELECT"
- [ ] Select-all checkbox in the header checks/unchecks all file checkboxes
- [ ] Exiting select mode unchecks all checkboxes
- [ ] DELETE ALL button deletes all files after confirmation ("Delete all files?")
- [ ] Flash message shows count of deleted files

### Bulk Download & Delete (when files are selected)
- [ ] Download selected: creates a ZIP file named `STUDS_files_YYYYMMDD_HHMMSS.zip` containing the selected files
- [ ] Delete selected: deletes only the checked files, shows count in flash message

### OmniCounts File Generator (on Files page)
- [ ] Form with file input (accepts `.csv`), store number text field, and GENERATE button
- [ ] Store number validated client-side (digits only) and server-side
- [ ] Upload a Brightpearl full inventory summary CSV
- [ ] Filters uploaded CSV to only SKUs present in the current weekly SKU list (via `scan_input_files()` and `load_sku_list()`)
- [ ] RS-prefixed SKUs are excluded
- [ ] Missing SKUs (in weekly list but not in CSV) are appended as placeholder rows with `0` for numeric columns and descriptions from `SKU_Master.csv`
- [ ] Returns a download named `{store_number}_OnHands.csv`
- [ ] Flash error if no weekly SKU list file exists in `/input/`
- [ ] Flash error if uploaded CSV has no SKU column

---

## HQ Database (`/hq/?section=database`)

### Master SKU File Section
- [ ] Displays: filename (SKU_Master.csv), SKU count, last updated timestamp
- [ ] File upload input accepts `.csv` files
- [ ] UPLOAD button submits the new master file
- [ ] Old master file is archived before overwrite
- [ ] After upload, image/SKU audit runs automatically
- [ ] Flash message confirms update with count of SKUs added and removed

### Product Images Section
- [ ] Displays count of images in `/database/images/`
- [ ] File upload input accepts `.jpg, .jpeg, .png, .webp`, supports multiple files
- [ ] UPLOAD button submits the images
- [ ] After upload, image/SKU audit runs automatically
- [ ] Flash message confirms count of images uploaded

### Image/SKU Audit Section
- [ ] Displays summary: X orphaned images, Y SKUs missing images
- [ ] If all matched: "All SKUs and images are matched."

### Orphaned Images Table (if any)
- [ ] Columns: Preview (thumbnail) | Filename | Assign to SKU | Actions
- [ ] Preview shows the actual image from `/database/images/`
- [ ] Each row has a text input for a SKU and an ASSIGN button
- [ ] Assigning renames the image file to `[SKU].[ext]` and marks the flag as resolved
- [ ] Each row has a DISCONTINUE button that marks the flag as discontinued
- [ ] After assign or discontinue, audit re-runs and page redirects

### Missing Images Table (if any)
- [ ] Columns: SKU | Description | Status
- [ ] Status shows "No image on file" for each

---

## HQ Settings

### Settings Hub (`/hq/settings`)
- [ ] Displays two navigation cards with arrow indicators
- [ ] "Login Credentials" card links to `/hq/settings/credentials`
- [ ] "Email Settings" card links to `/hq/settings/email`

### Login Credentials (`/hq/settings/credentials`)
- [ ] Table with one row per studio (all 40 stores)
- [ ] Each row shows: Store name, Username input, Password input
- [ ] Username inputs are pre-populated with current values
- [ ] Password inputs are blank with placeholder "Leave blank to keep"
- [ ] SAVE button submits the form
- [ ] Only non-empty username fields are updated
- [ ] Only non-empty password fields are updated (hashed with bcrypt)
- [ ] Flash message: "Credentials updated." or "No changes made."
- [ ] Redirects back to the same page after save

### Email Settings (`/hq/settings/email`)
- [ ] Email template textarea for customizing the email body
- [ ] Help text explains `{{sku_table}}` placeholder usage
- [ ] Table with one row per studio for setting email addresses
- [ ] Each row shows: Store name, Email input (placeholder shows default format)
- [ ] SAVE button submits the form
- [ ] Saves email template and all per-store emails to settings.json
- [ ] Flash message: "Email settings saved."
- [ ] Redirects back to the same page after save

---

## HQ Archive (`/hq/archive`)

- [ ] Displays last 50 archived files sorted by most recent first
- [ ] Table columns: File Type | Original Filename | Store | Archived At | Row Count | Size
- [ ] Archives are created automatically when files are overwritten (MSF uploads, input file uploads)

---

## Studio Portal (`/studio/`)

### Header
- [ ] Left nav box (lime): LOGOUT (or HQ | LOGOUT if admin user)
- [ ] Center: STUDS logo with "(CONFIDENTIAL)"
- [ ] Right nav box (lavender): PRINT button (only shown if SKU list exists)
- [ ] SKU list filename displayed below header

### Empty State
- [ ] If no SKU list file exists, displays a message indicating no active SKU list

### Search
- [ ] Search input field filters SKU cards in real-time
- [ ] Filters by SKU code or description (case-insensitive)
- [ ] Displays count of visible/matching SKUs, updates dynamically

### SKU Card Grid
- [ ] Responsive grid layout of product cards
- [ ] Each card shows: product image (or "No image" placeholder), SKU code, description, barcode
- [ ] Images are loaded from `/database/images/` matching the SKU prefix (case-insensitive)
- [ ] Barcodes generated client-side using JsBarcode (CODE128 format, 28px height, no text)
- [ ] Cards have data attributes for SKU and description for search filtering

### Print Functionality
- [ ] If no search is active, clicking PRINT immediately calls `window.print()`
- [ ] If a search filter is active, clicking PRINT opens a print options modal
- [ ] Modal offers two options: "PRINT ALL [X] SKUS" and "PRINT [X] MATCHING SKUS"
- [ ] Print All temporarily shows all cards, prints, then restores filter
- [ ] Print Filtered prints only the currently visible cards
- [ ] Cancel link closes the modal
- [ ] Clicking outside the modal closes it
- [ ] Print-specific stylesheet shows a "STUDS" header visible only on paper

### Tutorial Page (`/studio/tutorial`)
- [ ] Dedicated page accessible via TUTORIAL navlink in the Studio header (lavender button, left of OMNICOUNTS)
- [ ] TUTORIAL navlink appears on all Studio pages (main, OmniCounts, Tutorial)
- [ ] Header matches Studio sub-page layout (left: HQ/LOGOUT, center: STUDS logo, right: STUDIO link back)
- [ ] Sub-header label shows "TUTORIAL"
- [ ] Single-page multi-step walkthrough; one step visible at a time
- [ ] Intro screen (no step number): heading "Hey, Stud!", four-item checkbox checklist, begin button
- [ ] Step 1: Brightpearl Inventory Summary — instructions with numbered sub-list, link to Brightpearl
- [ ] Step 2: Converting to OmniCounts File — instructions with link to /studio/omnicounts (opens new tab)
- [ ] Step 3: Data Dumping into Filezilla — placeholder text "(Jasmine to add more details here later...)"
- [ ] Step 4: Printing SKU List — instructions for printing/scanning barcodes
- [ ] Step 5: Begin your count — placeholder text
- [ ] Step 6: Close Out Your Count — placeholder text
- [ ] Step 7: Reconcile variances — instructions referencing handoffs@omnicounts.com variance email
- [ ] Step 8: Check for major variances — recount instruction
- [ ] Step 9: Make adjustments in Brightpearl — final step with completion message, no next button
- [ ] Clicking next button hides current step and shows next step, scrolls to top
- [ ] No persistence — refreshing returns to intro
- [ ] Checkboxes on intro are visual only, no state tracked

### OmniCounts Page (`/studio/omnicounts`)
- [ ] Dedicated page accessible via OMNICOUNTS navlink in the Studio header (lavender button, left of PRINT)
- [ ] OMNICOUNTS navlink is always visible (not conditional on SKU list existence)
- [ ] Header matches Studio main page layout (left: HQ/LOGOUT, center: STUDS logo, right: STUDIO link back)
- [ ] Sub-header label shows "OMNICOUNTS" instead of "STUDIO"
- [ ] Form with file input (accepts `.csv`), store number text field, and GENERATE button
- [ ] Store number validated client-side (digits only) and server-side
- [ ] Upload a Brightpearl full inventory summary CSV
- [ ] Filters uploaded CSV to only SKUs present in the current weekly SKU list (via `scan_input_files()` and `load_sku_list()`)
- [ ] RS-prefixed SKUs are excluded
- [ ] Missing SKUs (in weekly list but not in CSV) are appended as placeholder rows with `0` for numeric columns and descriptions from `SKU_Master.csv`
- [ ] Returns a download named `{store_number}_OnHands.csv`
- [ ] Flash error if no weekly SKU list file exists in `/input/`
- [ ] Flash error if uploaded CSV has no SKU column
- [ ] Generation logic is identical to the HQ version (shared helper function)

---

## Reconciliation Logic (observable effects)

- [ ] SKUs with RS prefix are excluded from all reconciliation
- [ ] Variance files must contain columns: Sku, Description, Counted Units, Onhand Units, Unit Variance
- [ ] Audit trail entries are matched by warehouse ID (numeric prefix, zero-padded to 3 digits)
- [ ] Only audit trail rows with reference containing "stock update" or "stock check" (case-insensitive) count as actual pushes
- [ ] Required push = Unit Variance from variance file
- [ ] Actual push = sum of matching audit trail quantities for that SKU and store
- [ ] Discrepancy = Required Push - Actual Push
- [ ] Store status: "Updated" if zero discrepancies, "Discrepancy Detected" if any non-zero
- [ ] Stores without a variance file get "Incomplete (missing file)"
- [ ] Stores with unrecognized variance file schema get "Incomplete (unrecognized file format)"
- [ ] Multiple SKU lists: most recent (by filename date) is used, warning shown
- [ ] Multiple audit trails: most recent (by filename date) is used, warning shown
- [ ] Store list always includes all 40 seeded stores from database, regardless of file presence

---

## Global Behaviors

### Column Sorting (all tables app-wide)
- [ ] Sortable columns indicated by clickable headers
- [ ] Supports data types: string (case-insensitive), number (parses floats), percent (strips %)
- [ ] First click sorts ascending, second click sorts descending, toggles on repeat
- [ ] Sort direction indicator arrow (up/down unicode) appended to active column header
- [ ] Previous sort indicators are removed when sorting a different column

### Context Processor (all pages)
- [ ] `current_user_name` injected into all templates (from session display_name)
- [ ] `last_loaded_global` timestamp injected into all templates

### Image Serving
- [ ] Product images served from `/database/images/<filename>` (no authentication required)
