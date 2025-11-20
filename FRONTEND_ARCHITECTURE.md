# RadIMO SBZ Frontend Architecture - Comprehensive Analysis

## 1. CURRENT FRONTEND ORGANIZATION: Modality-Based with All Skills

The RadIMO system is organized by **modality** (CT, MR, XRAY) with all skills available within each modality. Each user navigates to a specific modality view and can interact with all configured skills.

### Frontend Navigation Structure:

```
Main Entry Point (/) ─────────────────────────────────────────
    │
    ├─── [Modality Selector Navigation Buttons]
    │    CT | MR | XRAY
    │
    └─── Modality-Specific View
         └─── Skill Buttons (all available skills)
              Normal | Notfall | Privat | Herz | Msk | Chest
              
         └─── Admin Portal (/upload)
         └─── Timetable (/timetable)
```

### Directory Structure:

```
/home/user/RadIMO_SBZ_DEV/
├── app.py                    # Main Flask application (2141 lines)
├── config.yaml              # Configuration for modalities, skills, balancer
├── templates/               # HTML templates
│   ├── index.html          # Main assignment interface
│   ├── upload.html         # Admin panel with statistics
│   ├── timetable.html      # Timeline visualization
│   └── login.html          # Authentication
└── static/                 # Static assets
    ├── vis.js              # Timeline library (1.8MB unminified)
    ├── vis.min.js          # Timeline library minified (675KB)
    ├── vis.min.css         # Timeline styles
    ├── favicon.ico         # App icon
    └── EULA.txt, verfahrensverzeichniss.txt
```

---

## 2. MAIN HTML TEMPLATES AND STRUCTURE

### A. /templates/index.html - Main Assignment Interface

**File Path:** `/home/user/RadIMO_SBZ_DEV/templates/index.html` (483 lines)

**Purpose:** Primary interface where users request workers for specific skills/modalities.

**Key Structure:**
```html
<body data-modality="{{ modality }}">
  <!-- Premium Header with Modality Selector -->
  <header class="premium-header">
    <h1>RadIMO: {{ modality_labels[modality] }} Koordinator</h1>
    <div class="modality-selector">
      <!-- Dynamic links for each modality -->
      {% for mod in modality_order %}
        <a href="{{ url_for('index', modality=mod) }}" 
           data-modality="{{ mod }}" 
           class="{% if modality == mod %}active{% endif %}">
          {{ modality_labels[mod] }}
        </a>
      {% endfor %}
    </div>
  </header>

  <!-- Main Assignment Panel -->
  <section class="card">
    <div id="buttonGrid" class="button-grid">
      <!-- Dynamic Skill Buttons -->
      {% for skill in skill_definitions %}
        <div class="skill-button-wrapper" data-skill-slug="{{ skill.slug }}">
          <button id="skill-btn-{{ skill.slug }}"
                  data-skill-name="{{ skill.name }}"
                  onclick="getNextAssignment('{{ skill.name }}')"
                  class="btn assignment-btn skill-main-btn">
            {{ skill.label }}
          </button>
          <!-- Strict mode button (no fallback) -->
          <button onclick="getNextAssignment('{{ skill.name }}', true)"
                  class="btn assignment-btn skill-strict-btn">
            *
          </button>
        </div>
      {% endfor %}
    </div>

    <!-- Result Panel -->
    <div id="result"></div>

    <!-- Clipboard Note -->
    <div class="clipboard-note">
      <span>Kürzel wird automatisch kopiert...</span>
      <div>
        <a href="{{ url_for('timetable', modality=modality) }}" class="small-button">
          Zeitplan
        </a>
        <a href="{{ url_for('upload_file', modality=modality) }}" class="small-button">
          Admin
        </a>
      </div>
    </div>

    <!-- Info Texts Display -->
    <div class="info-box">
      <div class="info-texts">
        {% for info in info_texts %}
          <div class="info-item">{{ info }}</div>
        {% endfor %}
      </div>
    </div>
  </section>

  <!-- Click History Visualization -->
  <div class="click-history-wrapper">
    <div id="clickHistory" class="click-history"></div>
    <div class="click-history-text">
      <div class="radimo">RadIMO v17</div>
      <div class="subtitle">Radiology: Innovation, Management & Orchestration</div>
    </div>
  </div>
</body>
```

**CSS Styling:**
- CSS Variables for theme (modality colors)
- 3-column grid layout for skill buttons
- Responsive design with max-width 1000px
- Dynamic modality background colors applied via data-attribute selector

**Key CSS Classes:**
```css
.button-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
}

.btn {
  min-height: 120px;
  font-size: 2rem;
  font-weight: 600;
}

.skill-button-wrapper {
  display: flex;
  gap: 0.4rem;
}

.skill-main-btn { flex: 1 1 66%; }
.skill-strict-btn { flex: 0 0 34%; filter: brightness(0.85); }

.result-panel { text-align: center; padding: 1rem; }
.assigned-person { font-size: 2rem; font-weight: 600; }
```

---

### B. /templates/upload.html - Admin Panel

**File Path:** `/home/user/RadIMO_SBZ_DEV/templates/upload.html` (963 lines)

**Purpose:** Administrative interface for managing Excel files, viewing statistics, and editing shifts.

**Key Sections:**

1. **Operational Checks Section:**
```html
{% if operational_checks %}
<section class="card operational-checks">
  <h2>Systemchecks</h2>
  <ul class="operational-checks-list">
    {% for result in operational_checks.results %}
      <li class="operational-check-item {{ result.status|lower }}">
        <strong>{{ result.name }}</strong>
        <span class="operational-check-status">{{ result.status }}</span>
        <div class="operational-check-detail">{{ result.detail }}</div>
      </li>
    {% endfor %}
  </ul>
  <div class="operational-check-timestamp">
    Letzter Lauf ({{ operational_checks.context }}): 
    {{ operational_checks.timestamp }}
  </div>
</section>
{% endif %}
```

2. **Statistics Table:**
```html
<div class="card">
  <h2>Statistiken</h2>
  <table>
    <thead>
      <tr>
        <th>MA</th>
        {% for skill in skill_definitions %}
          <th>{{ skill.label }}</th>
        {% endfor %}
        <th>∑</th>
        <th>W (Global)</th>
      </tr>
    </thead>
    <tbody id="modalityStatsBody">
      <!-- Dynamically populated by JavaScript -->
    </tbody>
  </table>
</div>
```

3. **File Upload Section:**
```html
<div class="card file-upload-card">
  <h2>Datei Upload</h2>
  <form action="{{ url_for('upload_file', modality=modality) }}" 
        method="post" 
        enctype="multipart/form-data">
    <input type="file" name="file" accept=".xlsx">
    <label>
      <input type="radio" name="scheduled_upload" value="0" checked> 
      Sofort
    </label>
    <label>
      <input type="radio" name="scheduled_upload" value="1"> 
      07:30 (Scheduled)
    </label>
    <button type="submit" class="upload-button">Upload</button>
    <a href="{{ url_for('download_file', modality=modality) }}">
      Download Letzte
    </a>
    <a href="{{ url_for('download_latest', modality=modality) }}">
      Download Live-Backup
    </a>
  </form>
</div>
```

4. **Edit Entry Form:**
```html
<div class="card">
  <h2>Bearbeiten der Einträge</h2>
  <form action="{{ url_for('edit_entry') }}" method="post">
    <input type="number" id="index" name="index" placeholder="Index">
    <input type="text" id="person" name="person" placeholder="Name (Kürzel)">
    <input type="text" id="time" name="time" placeholder="07:00-14:00">
    <input type="text" id="modifier" name="modifier" placeholder="1.0">
    
    <!-- Skill toggles -->
    {% for skill in skill_definitions %}
      <label>{{ skill.label }}:</label>
      <select name="{{ skill.form_key }}">
        <option value="0">0</option>
        <option value="1">1</option>
        <option value="2">2</option>
      </select>
    {% endfor %}
    
    <button type="submit">Aktualisieren/Hinzufügen</button>
    <button type="button" onclick="deleteEntry()">Löschen</button>
  </form>
</div>

<!-- Legend: Skill Value Meaning -->
<small>Gewichtung: 0 = Ausschluss, 1 = Normale Einteilung, 2 = Bevorzugt</small>
```

5. **Timeline Visualization:**
```html
<div class="card timeline-card">
  <h2>Zeitplan</h2>
  <div id="timeline-container"></div>
  <div class="legend">
    {% for skill in skill_definitions %}
      <div class="legend-item">
        <div class="legend-box" style="background: {{ skill.button_color }};"></div>
        {{ skill.label }}
      </div>
    {% endfor %}
  </div>
</div>
```

6. **Summary Statistics (Full Stats):**
```html
<button onclick="toggleSummaryStats()" class="modality-button">
  Full Stats
</button>

<div id="summaryStatsContainer" class="card" style="display: none;">
  <h2>Zusammenfassung (Gesamtstatistik)</h2>
  <table>
    <thead>
      <tr>
        <th>MA</th>
        {% for mod in modality_order %}
          <th>{{ modality_labels[mod] }}</th>
        {% endfor %}
        <th>∑</th>
        <th>W (Global)</th>
      </tr>
    </thead>
    <tbody id="summaryStatsBody">
      <!-- Cross-modality statistics -->
    </tbody>
  </table>
</div>
```

---

### C. /templates/timetable.html - Timeline View

**File Path:** `/home/user/RadIMO_SBZ_DEV/templates/timetable.html` (293 lines)

**Purpose:** Visual representation of worker schedules and skill availability over time.

**Key Components:**
```html
<body data-modality="{{ modality }}">
  <header class="premium-header">
    <h1>Zeitplan - {{ modality_labels[modality] }}</h1>
    <div class="modality-selector">
      {% for mod in modality_order %}
        <a href="{{ url_for('timetable', modality=mod) }}">
          {{ modality_labels[mod] }}
        </a>
      {% endfor %}
    </div>
  </header>

  <div class="card timeline-card">
    <div id="timeline-container"></div>
    <div class="legend">
      {% for skill in skill_definitions %}
        <div class="legend-item">
          <div class="legend-box" style="background: {{ skill.button_color }};"></div>
          {{ skill.label }}
        </div>
      {% endfor %}
    </div>
  </div>
</body>
```

**Uses:** VIS.js Timeline library for rendering time-based visualizations

---

### D. /templates/login.html - Authentication

**File Path:** `/home/user/RadIMO_SBZ_DEV/templates/login.html` (152 lines)

**Purpose:** Simple password authentication for admin access.

**Structure:**
```html
<div class="card login-container">
  <h2>Admin Login</h2>
  {% if error %}
    <p class="error">{{ error }}</p>
  {% endif %}
  <form method="post">
    <input type="password" name="password" placeholder="Passwort" required>
    <button type="submit" class="modality-button">Login</button>
    <a href="{{ url_for('index', modality=modality) }}" class="modality-button">
      Zurück
    </a>
  </form>
</div>
```

---

## 3. JAVASCRIPT/FRONTEND CODE HANDLING MODALITY-BASED VIEWS

### A. Main Script in index.html

**Location:** Inline JavaScript at bottom of index.html (lines 335-482)

**Key Functions:**

#### 1. Initialization and Auto-Reload
```javascript
document.addEventListener('DOMContentLoaded', function() {
  setInterval(quickReload, 60000);  // Refresh every 60 seconds
  quickReload();
});

function quickReload() {
  fetch('/api/quick_reload?modality={{ modality }}')
    .then(response => response.json())
    .then(data => {
      for (const [slug, isAvailable] of Object.entries(data.available_buttons)) {
        const wrapper = skillButtonMap[slug];
        if (wrapper) wrapper.style.display = isAvailable ? '' : 'none';
      }
    })
    .catch(e => console.error("Quick reload error:", e));
}
```

#### 2. Assignment Request Handler
```javascript
let requestInProgress = false;
let timerInterval, lastClickTime, disableTimeout;
let currentModality = "{{ modality }}";

const skillButtonMap = {};
document.querySelectorAll('.skill-button-wrapper').forEach(wrapper => {
  const slug = wrapper.dataset.skillSlug;
  if (slug) {
    skillButtonMap[slug] = wrapper;
  }
});

function getNextAssignment(skill, forcePrimary = false) {
  if (requestInProgress) return;
  updateButtonsState(true);
  
  const endpoint = forcePrimary
    ? `/api/${currentModality}/${skill}/strict`
    : `/api/${currentModality}/${skill}`;
    
  fetch(endpoint)
    .then(response => response.json())
    .then(data => {
      if (data['Assigned Person']) {
        showResult(data['Assigned Person']);
      }
    })
    .catch(e => {
      console.error("API error:", e);
      alert('Fehler beim Abrufen.');
    });
}
```

#### 3. Result Display with Automatic Clipboard Copy
```javascript
function showResult(person) {
  const resultDiv = document.getElementById('result');
  if (!person || person === "") {
    person = "Niemand verfügbar";
  }
  resultDiv.innerHTML = `
    <div class="result-panel">
      <div class="assigned-person">${person}</div>
      <div class="timer" id="timer"></div>
    </div>
  `;
  startTimer();
  
  // Extract abbreviation in parentheses and copy to clipboard
  const match = person.match(/\(([^)]+)\)/);
  if (match && match[1]) copyTextToClipboard(match[1]);
}

function copyTextToClipboard(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    document.execCommand('copy');
  } catch (e) {
    console.error(e);
  }
  document.body.removeChild(textarea);
}
```

#### 4. Timer Display
```javascript
function startTimer() {
  lastClickTime = new Date();
  updateTimer();
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = setInterval(updateTimer, 1000);
}

function updateTimer() {
  const now = new Date();
  const secondsElapsed = Math.floor((now - lastClickTime) / 1000);
  const hours = Math.floor(secondsElapsed / 3600);
  const minutes = Math.floor((secondsElapsed % 3600) / 60);
  const seconds = secondsElapsed % 60;
  
  document.getElementById('timer').textContent =
    "Zeit seit letzter Zuweisung: " +
    hours.toString().padStart(2, '0') + ":" +
    minutes.toString().padStart(2, '0') + ":" +
    seconds.toString().padStart(2, '0');
}
```

#### 5. Button State Management
```javascript
function updateButtonsState(disabled) {
  if (!disabled && requestInProgress) return;
  requestInProgress = disabled;
  
  document.querySelectorAll('.assignment-btn').forEach(button => {
    button.disabled = disabled;
    disabled ? button.classList.add('btn-disabled') : 
             button.classList.remove('btn-disabled');
  });
  
  if (disableTimeout) clearTimeout(disableTimeout);
  if (disabled) {
    disableTimeout = setTimeout(() => {
      requestInProgress = false;
      document.querySelectorAll('.assignment-btn').forEach(button => {
        button.disabled = false;
        button.classList.remove('btn-disabled');
      });
    }, 3000);  // Re-enable after 3 seconds
  }
}
```

#### 6. Click History Visualization
```javascript
const clickHistoryCount = 15;
const modalityBg = getComputedStyle(document.body)
  .getPropertyValue('--modality-bg').trim();
let clickHistoryColors = new Array(clickHistoryCount)
  .fill({ color: modalityBg });

function updateClickHistory(newColor) {
  const newEntry = { color: newColor };
  clickHistoryColors.pop();
  clickHistoryColors.unshift(newEntry);
  document.querySelectorAll('#clickHistory .click-history-box')
    .forEach((box, index) => {
      box.style.backgroundColor = clickHistoryColors[index].color;
      box.innerHTML = "";
    });
}

document.getElementById('buttonGrid').addEventListener('click', function(e) {
  const button = e.target.closest('button');
  if (button) {
    const bgColor = getComputedStyle(button).backgroundColor;
    updateClickHistory(bgColor);
  }
});
```

---

### B. Admin Panel JavaScript (upload.html)

**Location:** Inline script in upload.html (lines 609-904)

#### 1. File Upload Handler
```javascript
function updateFileName(input) {
  var fileName = input.files.length ? input.files[0].name : "Keine ausgewählt";
  document.getElementById("fileName").textContent = fileName;
}
```

#### 2. Edit Entry Loading
```javascript
function loadEntry() {
  const i = document.getElementById('index').value;
  if (i !== '') {
    fetch(`/get_entry?modality={{ modality }}&index=${i}`)
      .then(response => response.json())
      .then(data => {
        if (data.error) {
          alert(data.error);
        } else {
          document.getElementById('person').value = data.person;
          document.getElementById('time').value = data.time;
          const fieldKeys = ['modifier', ...skillFormKeys];
          fieldKeys.forEach(field => {
            document.getElementById(field).value = 
              (field in data) ? data[field] : 0;
          });
        }
      });
  }
}
```

#### 3. Timeline Building
```javascript
function buildTimeline() {
  const timelineContainer = document.getElementById('timeline-container');
  let dfData = JSON.parse('{{ debug_data|safe }}');
  
  dfData = dfData.filter(entry => entry.TIME !== '00:00-00:00');
  if (dfData.length === 0) {
    timelineContainer.innerHTML = "<p>No active schedule entries found</p>";
    return;
  }
  
  const items = [];
  const groups = [];
  const groupMap = {};
  
  // Build groups from data
  dfData.forEach((entry) => {
    const groupId = entry.PPL;
    const startTimeParts = entry.start_time.split(':');
    const startDateTime = new Date();
    startDateTime.setHours(parseInt(startTimeParts[0], 10), 
                          parseInt(startTimeParts[1], 10), 0);
    if (!groupMap[groupId]) {
      groupMap[groupId] = { id: groupId, order: startDateTime };
      groups.push(groupMap[groupId]);
    }
  });
  
  groups.sort((a, b) => a.order - b.order);
  const finalGroups = groups.map(group => ({ id: group.id, content: group.id }));
  
  // Build timeline items with skill gradients
  dfData.forEach((entry, index) => {
    const startTimeParts = entry.start_time.split(':');
    const endTimeParts = entry.end_time.split(':');
    const startDateTime = new Date();
    startDateTime.setHours(parseInt(startTimeParts[0], 10), 
                          parseInt(startTimeParts[1], 10), 0);
    const endDateTime = new Date();
    endDateTime.setHours(parseInt(endTimeParts[0], 10), 
                        parseInt(endTimeParts[1], 10), 0);
    
    // Determine active skills
    const activeSkills = [];
    skillColumns.forEach(skillName => {
      if (entry[skillName] > 0) {
        const slug = skillSlugMap[skillName] || skillName.toLowerCase();
        activeSkills.push(slug);
      }
    });
    
    // Create dynamic styling for skill visualization
    const customClass = `timeline-item-${index}`;
    const customStyle = document.createElement('style');
    customStyle.textContent = `.${customClass} { ${buildGradient(activeSkills)} }`;
    document.head.appendChild(customStyle);
    
    items.push({
      id: index,
      group: entry.PPL,
      start: startDateTime,
      end: endDateTime,
      content: '',
      title: `${entry.PPL}<br>Zeit: ${entry.TIME}<br>Skills: ${activeSkills.join(', ')}`,
      className: customClass
    });
  });
  
  const today = new Date();
  const options = {
    zoomable: false,
    moveable: true,
    stack: false,
    min: new Date(today.setHours(7, 0, 0)),
    max: new Date(today.setHours(20, 0, 0)),
    showCurrentTime: true,
    format: {
      minorLabels: { hour: 'HH:mm', minute: 'HH:mm' }
    },
    orientation: { axis: 'top', item: 'top' },
    margin: { item: { vertical: 10 } },
    verticalScroll: true,
  };
  
  const timeline = new vis.Timeline(timelineContainer, items, finalGroups, options);
  setInterval(() => {
    timeline.setCurrentTime(new Date());
  }, 60000);
}
```

#### 4. Skill Gradient Building for Timeline
```javascript
function buildGradient(skills) {
  const stripeWidth = 10;
  const gapWidth = 15;
  if (!skills || skills.length === 0) {
    return "background: #ffffff;";
  }
  const colors = skills.map(slug => skillColorMap[slug] || '#cccccc');
  if (colors.length === 1) {
    const color = colors[0];
    return `background: repeating-linear-gradient(
      90deg,
      ${color} 0px,
      ${color} ${stripeWidth}px,
      #ffffff ${stripeWidth}px,
      #ffffff ${stripeWidth + gapWidth}px
    );`;
  }
  const stops = colors.map((color, idx) => {
    const start = idx * stripeWidth;
    const end = start + stripeWidth;
    return `${color} ${start}px, ${color} ${end}px`;
  });
  const blockWidth = colors.length * stripeWidth;
  stops.push(`#ffffff ${blockWidth}px, #ffffff ${blockWidth + gapWidth}px`);
  const period = blockWidth + gapWidth;
  return `background: repeating-linear-gradient(
    90deg, ${stops.join(', ')}, #ffffff ${period}px
  );`;
}
```

#### 5. Statistics Update (Modality-Specific)
```javascript
function updateUploadStats() {
  fetch(`/api/quick_reload?modality={{ modality }}`)
    .then(response => response.json())
    .then(data => {
      let modalityRows = "";
      const workers = Object.keys(data.Summe).sort((a, b) =>
        data.Summe[b] - data.Summe[a] || a.localeCompare(b)
      );

      workers.forEach(worker => {
        modalityRows += `<tr class="stats-row"><td>${worker}</td>`;

        let totalForWorker = 0;

        skillColumns.forEach(skill => {
          const currentModCount = (data[skill] && data[skill][worker]) 
            ? data[skill][worker] : 0;
          const globalModCount = data.Global[worker]?.[skill] || 0;
          const extraCount = globalModCount - currentModCount;

          let displayValue = currentModCount;
          if (extraCount > 0) {
            displayValue += ` (+${extraCount})`;
          }
          modalityRows += `<td>${displayValue}</td>`;
          totalForWorker += currentModCount;
        });

        const currentModTotal = data.Summe[worker] || 0;
        const globalModTotal = data.Global[worker]?.total || 0;
        const totalExtra = globalModTotal - currentModTotal;

        let displayTotal = currentModTotal;
        if (totalExtra > 0) {
          displayTotal += ` (+${totalExtra})`;
        }

        const globalWeighted = (data.GlobalWeighted && 
          data.GlobalWeighted[worker] !== undefined) 
          ? parseFloat(data.GlobalWeighted[worker]).toFixed(1) 
          : "N/A"; 

        modalityRows += `<td>${displayTotal}</td><td>${globalWeighted}</td></tr>`;
      });

      document.getElementById("modalityStatsBody").innerHTML = modalityRows;
    })
    .catch(error => console.error("Error updating stats:", error));
}
```

#### 6. Summary Statistics (Cross-Modality)
```javascript
const summaryModalities = {{ modality_order|tojson }};

function updateSummaryTable() {
  const fetchPromises = summaryModalities.map(mod =>
    fetch(`/api/quick_reload?modality=${mod}`)
      .then(r => r.json())
      .catch(error => {
        console.error(`Error loading summary stats for ${mod}:`, error);
        return null;
      })
  );

  Promise.all(fetchPromises)
    .then(results => {
      const summaryData = {};
      const allWorkers = new Set();
      const modalityDataMap = {};

      summaryModalities.forEach((mod, index) => {
        const modData = results[index] || {};
        modalityDataMap[mod] = modData;
        Object.keys(modData.Summe || {}).forEach(worker => 
          allWorkers.add(worker)
        );
      });

      allWorkers.forEach(worker => {
        summaryData[worker] = { total: 0, weighted: 0 };
        summaryModalities.forEach(mod => {
          const dataForMod = modalityDataMap[mod] || {};
          const sumValue = dataForMod.Summe && dataForMod.Summe[worker]
            ? parseInt(dataForMod.Summe[worker])
            : 0;
          summaryData[worker][mod] = sumValue;
          summaryData[worker].total += sumValue;

          const weightedValue = dataForMod.GlobalWeighted && 
            dataForMod.GlobalWeighted[worker]
            ? parseFloat(dataForMod.GlobalWeighted[worker])
            : 0;
          if (!isNaN(weightedValue)) {
            summaryData[worker].weighted = 
              Math.max(summaryData[worker].weighted, weightedValue);
          }
        });
      });

      let sortedWorkers = Object.keys(summaryData).sort((a, b) =>
        summaryData[b].weighted - summaryData[a].weighted
      );

      let summaryRows = "";
      sortedWorkers.forEach(worker => {
        summaryRows += `<tr class="stats-row"><td>${worker}</td>`;
        summaryModalities.forEach(mod => {
          summaryRows += `<td>${summaryData[worker][mod] || 0}</td>`;
        });
        summaryRows += `<td>${summaryData[worker].total}</td>`;
        summaryRows += `<td>${summaryData[worker].weighted.toFixed(1)}</td></tr>`;
      });

      document.getElementById("summaryStatsBody").innerHTML = summaryRows;
    })
    .catch(error => console.error("Error updating summary stats:", error));
}

// Auto-refresh every 60 seconds
document.addEventListener("DOMContentLoaded", function() {
  updateSummaryTable();
  setInterval(updateSummaryTable, 60000);
});
```

---

## 4. NAVIGATION BETWEEN MODALITIES

### A. Template-Level Navigation

All templates (index.html, upload.html, timetable.html, login.html) include a **Modality Selector** in the header:

```html
<div class="modality-selector">
  {% for mod in modality_order %}
    <a href="{{ url_for('<current_page>', modality=mod) }}" 
       data-modality="{{ mod }}" 
       class="{% if modality == mod %}active{% endif %}">
      {{ modality_labels[mod] }}
    </a>
  {% endfor %}
</div>
```

**Navigation Flow:**
- Clicking a modality tab navigates to the same page but with different modality parameter
- Example: `/index?modality=ct` → `/index?modality=mr`
- The page re-renders with modality-specific data

### B. URL Routing Pattern

All routes support modality query parameter:
```
/?modality=ct
/?modality=mr
/?modality=xray

/upload?modality=ct
/timetable?modality=xray
/login?modality=mr
```

### C. Backend Modality Resolution

**Function:** `resolve_modality_from_request()` in app.py (lines 469-470)

```python
def resolve_modality_from_request() -> str:
    return normalize_modality(request.values.get('modality'))

def normalize_modality(modality_value: Optional[str]) -> str:
    if not modality_value:
        return default_modality
    modality_value = modality_value.lower()
    return modality_value if modality_value in allowed_modalities else default_modality
```

### D. CSS Active State

```css
.modality-selector a {
  border: 2px solid;
  border-color: {{ settings.nav_color }};  /* Modality-specific color */
  transition: border-width 0.2s;
}

.modality-selector a.active {
  border-width: 4px;  /* Thicker border for active modality */
}
```

---

## 5. API ENDPOINTS CALLED BY FRONTEND

### A. Worker Assignment Endpoints

**Primary Assignment Request (with fallback):**
```
GET /api/{modality}/{role}
GET /api/ct/Normal
GET /api/mr/Notfall
GET /api/xray/Herz
```

**Strict Assignment Request (no fallback):**
```
GET /api/{modality}/{role}/strict
GET /api/ct/Normal/strict
```

**Backend Handler:** `assign_worker_api()` (lines 1730-1743)
```python
@app.route('/api/<modality>/<role>', methods=['GET'])
def assign_worker_api(modality, role):
    modality = modality.lower()
    if modality not in modality_data:
        return jsonify({"error": "Invalid modality"}), 400
    return _assign_worker(modality, role)

@app.route('/api/<modality>/<role>/strict', methods=['GET'])
def assign_worker_strict_api(modality, role):
    modality = modality.lower()
    if modality not in modality_data:
        return jsonify({"error": "Invalid modality"}), 400
    return _assign_worker(modality, role, allow_fallback=False)
```

**Response Structure:**
```json
{
  "Draw Time": "14:30:45",
  "Assigned Person": "Max Mustermann (MM)",
  "Summe": {
    "Max Mustermann": 5,
    "John Doe": 3,
    ...
  },
  "Global": {
    "Max Mustermann": {
      "Normal": 5,
      "Notfall": 2,
      "Herz": 1,
      ...
      "total": 8
    },
    ...
  },
  "modality_used": "ct",
  "skill_used": "Normal",
  "modality_requested": "ct",
  "fallback_allowed": true,
  "strict_request": false,
  "Normal": { "Max Mustermann": 5, ... },
  "Notfall": { ... },
  ...
}
```

### B. Quick Reload Endpoint

**Purpose:** Refresh available buttons and worker statistics every 60 seconds

```
GET /api/quick_reload?modality=ct
```

**Backend Handler:** `quick_reload()` (lines 2050-2114)

```python
@app.route('/api/quick_reload', methods=['GET'])
def quick_reload():
    modality = resolve_modality_from_request()
    d = modality_data[modality]
    now = get_local_berlin_now()
    checks = run_operational_checks('reload', force=True)
    
    # Determine available buttons based on currently active working hours
    available_buttons = {SKILL_SLUG_MAP[skill]: False for skill in SKILL_COLUMNS}
    if d['working_hours_df'] is not None:
        tnow = now.time()
        active_df = d['working_hours_df'][
            (d['working_hours_df']['start_time'] <= tnow) &
            (d['working_hours_df']['end_time'] >= tnow)
        ]
        for skill in SKILL_COLUMNS:
            slug = SKILL_SLUG_MAP[skill]
            available_buttons[slug] = bool(
                (skill in active_df.columns) and (active_df[skill].sum() > 0)
            )
    
    # Returns worker statistics and operational checks
    return jsonify({
        "Draw Time": now.strftime("%H:%M:%S"),
        "Assigned Person": None,
        "Summe": sum_counts,
        "Global": global_stats,
        "GlobalWeighted": global_weighted_counts,
        "available_buttons": available_buttons,
        "operational_checks": checks,
    })
```

**Response Structure:**
```json
{
  "Draw Time": "14:30:45",
  "Assigned Person": null,
  "Summe": {
    "Max Mustermann": 5,
    ...
  },
  "Global": { ... },
  "GlobalWeighted": {
    "Max Mustermann": 6.5,
    ...
  },
  "available_buttons": {
    "normal": true,
    "notfall": true,
    "herz": false,
    ...
  },
  "operational_checks": {
    "results": [...],
    "timestamp": "2025-11-20 14:30:45",
    "context": "reload"
  }
}
```

### C. Admin/Upload Endpoints

**Get Entry Data:**
```
GET /get_entry?index=0&modality=ct
```

**Response:**
```json
{
  "person": "Max Mustermann (MM)",
  "time": "07:00-14:00",
  "modifier": 1.0,
  "normal": 1,
  "notfall": 1,
  "herz": 0,
  ...
}
```

**Edit/Update Entry:**
```
POST /edit
Content-Type: application/x-www-form-urlencoded

index=0&person=Max%20Mustermann&time=07:00-14:00&modifier=1.0&normal=1&...
```

**Delete Entry:**
```
POST /delete
Content-Type: application/x-www-form-urlencoded

index=0
```

**File Upload:**
```
POST /upload
Content-Type: multipart/form-data

file: <xlsx file>
scheduled_upload: 0|1
```

**Download File:**
```
GET /download              # Last uploaded file
GET /download_latest       # Live backup
```

**Edit Info Texts:**
```
POST /edit_info
Content-Type: application/x-www-form-urlencoded

info_text=<text with newlines>
```

---

## 6. WORK DISTRIBUTION VIEW IMPLEMENTATION

### A. Admin Statistics Panel

**Location:** upload.html (lines 374-424)

**Components:**

1. **Modality-Specific Statistics Table:**
   - Shows count of assignments per worker per skill
   - Shows sum total per worker
   - Shows global weighted count

```html
<table>
  <thead>
    <tr>
      <th>MA</th>
      {% for skill in skill_definitions %}
        <th>{{ skill.label }}</th>
      {% endfor %}
      <th>∑</th>
      <th>W (Global)</th>
    </tr>
  </thead>
  <tbody id="modalityStatsBody">
    <!-- Populated by updateUploadStats() JavaScript -->
  </tbody>
</table>
```

**Example Output:**
```
MA                Normal  Notfall  Privat  Herz  Msk  Chest  ∑   W(Global)
Max Mustermann      5       2        1      0     0    0    8    6.5
John Doe            3       1        0      1     0    0    5    4.2
Maria Schmidt       4       3        2      0     1    0   10    8.1
```

2. **Global Weighted Calculation Logic** (app.py, lines 1436-1450):

```python
def update_global_assignment(person: str, role: str, modality: str) -> str:
    """Update global assignment count with weighted calculation."""
    canonical_id = get_canonical_worker_id(person)
    
    # Get modifier (default 1.0)
    modifier = modality_data[modality]['worker_modifiers'].get(person, 1.0)
    modifier = _coerce_float(modifier, 1.0)
    
    # Calculate weighted value
    weight = skill_weights.get(role, 1.0) * modifier * modality_factors.get(modality, 1.0)
    
    # Update global counter
    global_worker_data['weighted_counts_per_mod'][modality][canonical_id] = \
        global_worker_data['weighted_counts_per_mod'][modality].get(canonical_id, 0.0) + weight
    
    # Update skill assignment count
    assignments = _get_or_create_assignments(modality, canonical_id)
    assignments[role] += 1
    assignments['total'] += 1
    
    return canonical_id
```

**Weight Formula:**
```
Weight = skill_weight × worker_modifier × modality_factor

Example:
  Notfall assignment for Max in CT modality:
  1.1 (Notfall) × 1.0 (modifier) × 1.0 (CT factor) = 1.1
  
  Herz assignment for Maria in MR modality:
  1.2 (Herz) × 1.5 (modifier if configured) × 1.2 (MR factor) = 2.16
```

### B. Cross-Modality Summary Statistics

**Location:** upload.html (lines 571-594)

**Toggle Button:**
```html
<button onclick="toggleSummaryStats()" class="modality-button">
  Full Stats
</button>

<div id="summaryStatsContainer" class="card" style="display: none;">
  <h2>Zusammenfassung (Gesamtstatistik)</h2>
  <table>
    <thead>
      <tr>
        <th>MA</th>
        {% for mod in modality_order %}
          <th>{{ modality_labels[mod] }}</th>
        {% endfor %}
        <th>∑</th>
        <th>W (Global)</th>
      </tr>
    </thead>
    <tbody id="summaryStatsBody">
      <!-- Populated by updateSummaryTable() JavaScript -->
    </tbody>
  </table>
</div>
```

**Example Output:**
```
MA                CT    MR    XRAY   ∑   W(Global)
Max Mustermann    8     2     0     10    8.5
John Doe          5     3     1      9    7.2
Maria Schmidt    10     4     2     16    12.3
```

### C. Timeline Visualization

**Location:** upload.html and timetable.html

**Purpose:** Visual representation of worker schedules with skill indicators

**Key Features:**
- Time-based horizontal axis (7:00-20:00)
- Worker/person on vertical axis
- Color-coded skill bars (striped for multiple skills)
- Interactive tooltips showing: Worker name, Time range, Skills active

**Visual Representation:**
```
Timeline Example:
Name          7:00  8:00  9:00  10:00 11:00 12:00 13:00 14:00 15:00 16:00 17:00
Max         [====Normal====][====Notfall====]
John          [====Normal====]
Maria       [=Normal=][==Herz==][========Notfall========]
```

**Gradient Color Mapping:**
- Each skill has its own color from config
- Multiple skills displayed as striped pattern
- Repeating pattern: 10px color, 15px white gap

**VIS.js Integration:**
```javascript
const timeline = new vis.Timeline(
  timelineContainer,
  items,        // Time entries with start/end times
  groups,       // Worker groups
  options       // Display options
);
```

### D. Active Worker Highlighting

**Location:** upload.html (lines 906-951)

**JavaScript Logic:**
```javascript
document.addEventListener("DOMContentLoaded", function() {
  const now = new Date();
  let activeWorkers = new Set();

  // Parse timeline data
  try {
    const timelineData = JSON.parse('{{ debug_data|safe }}') || [];
    timelineData.forEach(entry => {
      if (entry.TIME === '00:00-00:00') return;
      
      const start = new Date();
      const end = new Date();
      const [startHour, startMin] = entry.start_time.split(':');
      const [endHour, endMin] = entry.end_time.split(':');
      
      start.setHours(parseInt(startHour, 10), parseInt(startMin, 10), 0);
      end.setHours(parseInt(endHour, 10), parseInt(endMin, 10), 0);
      
      if (now >= start && now <= end) {
        activeWorkers.add(entry.PPL);
      }
    });
  } catch (e) {
    console.error("Error parsing debug_data:", e);
  }

  // Highlight active workers in statistics table
  document.querySelectorAll("#modalityStatsBody tr").forEach(row => {
    const worker = row.querySelector("td").textContent.trim();
    if (activeWorkers.has(worker)) {
      row.classList.add("active-row");
    }
  });
});
```

**CSS Highlighting:**
```css
.active-row {
  background-color: var(--modality-bg, #fff) !important;
}
```

### E. Skill Value System

**Displayed in Edit Form** (upload.html, lines 500-514):

```html
<select id="{{ skill.form_key }}" name="{{ skill.form_key }}">
  <option value="0">0</option>
  <option value="1">1</option>
  <option value="2">2</option>
</select>
```

**Skill Value Meanings** (legend in upload.html, line 521):
```
0 = Ausschluss       (Excluded - not available)
1 = Normale Einteilung (Active - normal priority)
2 = Bevorzugt        (Preferred - higher priority up to 125%)
```

**Backend Implementation** (app.py, lines 830-860):

```python
def _attempt_column_selection(
  active_df: pd.DataFrame, column: str, modality: str, is_primary: bool = True
):
    """
    Select workers from a specific skill column.

    Skill values:
    - 1 = Active (available for primary and fallback)
    - 0 = Passive (only available in fallback, not for primary requests)
    - -1 = Excluded (has skill but NOT available in fallback)
    """
    if column not in active_df.columns:
        return None

    # Filter based on primary vs fallback mode
    if is_primary:
        # Primary selection: only workers with value >= 1
        filtered_df = active_df[active_df[column] >= 1]
    else:
        # Fallback selection: workers with value >= 0
        filtered_df = active_df[active_df[column] >= 0]

    if filtered_df.empty:
        return None
    
    balanced_df = _apply_minimum_balancer(filtered_df, column, modality)
    result_df = balanced_df if not balanced_df.empty else filtered_df
    result_df = result_df.copy()
    result_df['__skill_source'] = column
    return result_df
```

---

## SUMMARY TABLE

| Aspect | Details |
|--------|---------|
| **Frontend Framework** | Jinja2 templates + vanilla JavaScript + CSS3 |
| **Modality Navigation** | Tab-based selector in header, URL parameter-based routing |
| **Main Views** | Home (assignment), Admin (stats & upload), Timetable (timeline), Login |
| **API Pattern** | RESTful GET/POST to Flask routes |
| **Real-time Updates** | Auto-refresh every 60 seconds via quick_reload endpoint |
| **Statistics** | Modality-specific + cross-modality tables with weighted counts |
| **Timeline Library** | VIS.js for time-based worker schedule visualization |
| **Skill Selection** | 3-value system (0=excluded, 1=active, 2=preferred) |
| **Work Distribution** | Weighted calculation: skill_weight × modifier × modality_factor |
| **File Format** | Excel (.xlsx) with Tabelle1 (data) and Tabelle2 (info) sheets |
| **Automatic Features** | Clipboard copy (abbreviations), Timer display, Active worker highlighting |

---

## KNOWN ISSUE

**Missing Function:** `run_operational_checks()` is called in app.py (lines 1712, 2055) but never defined. This function should return operational system check results. Current implementation will fail when trying to render the operational checks section.

