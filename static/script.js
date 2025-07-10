import * as d3 from "https://cdn.jsdelivr.net/npm/d3@7/+esm";
import { Marked } from "https://cdn.jsdelivr.net/npm/marked@13/+esm";
import hljs from "https://cdn.jsdelivr.net/npm/highlight.js@11/+esm";

const $demos = document.getElementById("demos");
const $hypotheses = document.getElementById("hypotheses");
const $hypothesisPrompt = document.getElementById("hypothesis-prompt");
const $synthesis = document.getElementById("synthesis");
const $synthesisResult = document.getElementById("synthesis-result");
const $status = document.getElementById("status");
const $filePath = document.getElementById("file-path");
const $loadFile = document.getElementById("load-file");
const loading = `<div class="text-center my-5"><div class="spinner-border" role="status"></div></div>`;

let data;
let description;
let hypotheses;

const marked = new Marked();
marked.use({
  renderer: {
    table(header, body) {
      return `<table class="table table-sm">${header}${body}</table>`;
    },
    code(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : "plaintext";
      return `<pre class="hljs language-${language}"><code>${hljs
        .highlight(code, { language })
        .value.trim()}</code></pre>`;
    },
  },
});

const numFormat = new Intl.NumberFormat("en-US", {
  style: "decimal",
  notation: "compact",
  compactDisplay: "short",
});
const num = (val) => numFormat.format(val);

// Settings management
function getSettings() {
  const defaults = {
    apiBaseUrl: "https://llmfoundry.straive.com/openai/v1",
    apiKey: "",
    modelName: "gpt-4.1-nano"
  };
  
  const stored = localStorage.getItem("hypoforge-settings");
  return stored ? { ...defaults, ...JSON.parse(stored) } : defaults;
}

function saveSettings(settings) {
  localStorage.setItem("hypoforge-settings", JSON.stringify(settings));
}

function validateSettings() {
  const settings = getSettings();
  if (!settings.apiKey) {
    $status.innerHTML = `<div class="alert alert-warning">
      <i class="bi bi-exclamation-triangle"></i>
      Please configure your API settings by clicking the Settings button in the navigation.
    </div>`;
    return false;
  }
  return true;
}

// Initialize settings UI
function initSettings() {
  const settings = getSettings();
  document.getElementById("apiBaseUrl").value = settings.apiBaseUrl;
  document.getElementById("apiKey").value = settings.apiKey;
  document.getElementById("modelName").value = settings.modelName;
}

// Settings modal handlers
document.getElementById("saveSettings").addEventListener("click", () => {
  const settings = {
    apiBaseUrl: document.getElementById("apiBaseUrl").value.trim(),
    apiKey: document.getElementById("apiKey").value.trim(),
    modelName: document.getElementById("modelName").value.trim()
  };
  
  if (!settings.apiBaseUrl || !settings.apiKey || !settings.modelName) {
    alert("Please fill in all required fields.");
    return;
  }
  
  saveSettings(settings);
  
  // Close modal
  const modal = bootstrap.Modal.getInstance(document.getElementById('settingsModal'));
  modal.hide();
  
  // Clear any existing warning
  $status.innerHTML = "";
});

// Initialize settings on page load
document.addEventListener("DOMContentLoaded", initSettings);

async function apiCall(endpoint, options = {}) {
  const response = await fetch(endpoint, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    },
    ...options
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'API call failed');
  }
  
  return response.json();
}

// Load configurations and render the demos
$status.innerHTML = loading;
const config = await apiCall('/config');
const { demos } = config;

$demos.innerHTML = demos
  .map(
    ({ title, body }, index) => `
      <div class="col py-3">
        <a class="demo card h-100 text-decoration-none" href="#" data-index="${index}">
          <div class="card-body">
            <h5 class="card-title">${title}</h5>
            <p class="card-text">${body}</p>
          </div>
        </a>
      </div>
    `
  )
  .join("");

const testButton = (index) =>
  `<button type="button" class="btn btn-sm btn-primary test-hypothesis" data-index="${index}">Test</button>`;

async function loadData(source) {
  if (typeof source === 'string') {
    // Handle file path
    const response = await apiCall('/load-file', {
      method: 'POST',
      body: JSON.stringify({ file_path: source })
    });
    return response;
  } else if (typeof source === 'object' && source.href) {
    // Handle demo data - fetch from URL and save to temp file, then load
    const response = await fetch(source.href);
    const blob = await response.blob();
    
    // For demo data, we'll need to handle this differently since we can't save arbitrary files
    // Instead, we'll fetch the data and process it directly
    const fileName = source.href.split('/').pop().toLowerCase();
    
    if (fileName.endsWith('.csv')) {
      const text = await response.text();
      const lines = text.split('\n');
      const headers = lines[0].split(',');
      const records = lines.slice(1).filter(line => line.trim()).map(line => {
        const values = line.split(',');
        const record = {};
        headers.forEach((header, i) => {
          const value = values[i]?.trim().replace(/"/g, '');
          // Try to parse as number, otherwise keep as string
          record[header.trim().replace(/"/g, '')] = isNaN(Number(value)) ? value : Number(value);
        });
        return record;
      });
      
      // Generate description
      const description = `The Pandas DataFrame df has ${records.length} rows and ${headers.length} columns:\n` +
        headers.map(col => `- ${col}: data column`).join('\n');
      
      return { data: records, description };
    } else {
      throw new Error('Demo database files not supported with file path method. Please use CSV demos or provide local file paths.');
    }
  }
}

// Handle file path load
$loadFile.addEventListener("click", async () => {
  const filePath = $filePath.value.trim();
  if (!filePath) {
    $status.innerHTML = `<div class="alert alert-warning">Please enter a file path</div>`;
    setTimeout(() => $status.innerHTML = "", 3000);
    return;
  }
  if (!validateSettings()) return;

  $status.innerHTML = loading;
  
  try {
    const result = await loadData(filePath);
    data = result.data;
    description = result.description;
    
    const systemPrompt = $hypothesisPrompt.value = "You are an expert data analyst. Generate hypotheses that would be valuable to test on this dataset. Each hypothesis should be clear, specific, and testable.";
    const settings = getSettings();
    
    $hypotheses.innerHTML = loading;
    
    const response = await apiCall('/generate-hypotheses', {
      method: 'POST',
      body: JSON.stringify({
        system_prompt: systemPrompt,
        description: description,
        api_base_url: settings.apiBaseUrl,
        api_key: settings.apiKey,
        model_name: settings.modelName
      })
    });
    
    hypotheses = response.hypotheses;
    drawHypotheses();
    $synthesis.classList.remove("d-none");
    $status.innerHTML = "";
  } catch (error) {
    $status.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
    setTimeout(() => $status.innerHTML = "", 5000);
  }
});
// Allow Enter key to trigger load
$filePath.addEventListener("keypress", (e) => {
  if (e.key === "Enter") {
    $loadFile.click();
  }
});

// When the user clicks on a demo, analyze it
$demos.addEventListener("click", async (e) => {
  e.preventDefault();
  const $demo = e.target.closest(".demo");
  if (!$demo) return;
  if (!validateSettings()) return;

  const demo = demos[+$demo.dataset.index];
  $status.innerHTML = loading;
  
  try {
    const result = await loadData(demo);
    data = result.data;
    description = result.description;
    
    const systemPrompt = $hypothesisPrompt.value = demo.audience;
    const settings = getSettings();
    
    $hypotheses.innerHTML = loading;
    const response = await apiCall('/generate-hypotheses', {
      method: 'POST',
      body: JSON.stringify({
        system_prompt: systemPrompt,
        description: description,
        api_base_url: settings.apiBaseUrl,
        api_key: settings.apiKey,
        model_name: settings.modelName
      })
    });
    
    hypotheses = response.hypotheses;
    drawHypotheses();
    $synthesis.classList.remove("d-none");
    $status.innerHTML = "";
  } catch (error) {
    $status.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
    setTimeout(() => $status.innerHTML = "", 5000);
  }
});

function drawHypotheses() {
  if (!Array.isArray(hypotheses)) return;
  $hypotheses.innerHTML = hypotheses
    .map(
      ({ hypothesis, benefit }, index) => `
      <div class="hypothesis col py-3" data-index="${index}">
        <div class="card h-100">
          <div class="card-body">
            <h5 class="card-title hypothesis-title">${hypothesis}</h5>
            <p class="card-text hypothesis-benefit">${benefit}</p>
          </div>
          <div class="card-footer">
            <div class="result">${testButton(index)}</div>
            <div class="outcome"></div>
          </div>
        </div>
      </div>
    `
    )
    .join("");
}

$hypotheses.addEventListener("click", async (e) => {
  const $hypothesis = e.target.closest(".test-hypothesis");
  if (!$hypothesis) return;
  if (!validateSettings()) return;
  
  const index = $hypothesis.dataset.index;
  const hypothesis = hypotheses[index];
  const analysisPrompt = document.getElementById("analysis-prompt").value;
  const settings = getSettings();

  const $resultContainer = $hypothesis.closest(".card");
  const $result = $resultContainer.querySelector(".result");
  const $outcome = $resultContainer.querySelector(".outcome");
  
  $outcome.innerHTML = loading;
  
  try {
    const response = await apiCall('/test-hypothesis', {
      method: 'POST',
      body: JSON.stringify({
        hypothesis: hypothesis.hypothesis,
        description: description,
        analysis_prompt: analysisPrompt,
        data: data,
        api_base_url: settings.apiBaseUrl,
        api_key: settings.apiKey,
        model_name: settings.modelName
      })
    });
    
    $outcome.classList.add(response.p_value < 0.05 ? "success" : "failure");
    $outcome.innerHTML = marked.parse(response.summary);
    $result.innerHTML = `<details>
      <summary class="h5 my-3">Analysis</summary>
      ${marked.parse(response.analysis)}
    </details>`;
  } catch (error) {
    $outcome.innerHTML = `<pre class="alert alert-danger">${error.message}</pre>`;
  }
});

document.querySelector("#run-all").addEventListener("click", async (e) => {
  const $hypotheses = [...document.querySelectorAll(".hypothesis")];
  const $pending = $hypotheses.filter((d) => !d.querySelector(".outcome").textContent.trim());
  $pending.forEach((el) => el.querySelector(".test-hypothesis").click());
});

document.querySelector("#synthesize").addEventListener("click", async (e) => {
  if (!validateSettings()) return;
  
  const hypotheses = [...document.querySelectorAll(".hypothesis")]
    .map((h) => ({
      title: h.querySelector(".hypothesis-title").textContent,
      benefit: h.querySelector(".hypothesis-benefit").textContent,
      outcome: h.querySelector(".outcome").textContent.trim(),
    }))
    .filter((d) => d.outcome);

  $synthesisResult.innerHTML = loading;
  
  try {
    const settings = getSettings();
    const response = await apiCall('/synthesize', {
      method: 'POST',
      body: JSON.stringify({ 
        hypotheses,
        api_base_url: settings.apiBaseUrl,
        api_key: settings.apiKey,
        model_name: settings.modelName
      })
    });
    
    $synthesisResult.innerHTML = marked.parse(response.synthesis);
  } catch (error) {
    $synthesisResult.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
  }
});

document.querySelector("#reset").addEventListener("click", async (e) => {
  for (const $hypothesis of document.querySelectorAll(".hypothesis")) {
    $hypothesis.querySelector(".result").innerHTML = testButton($hypothesis.dataset.index);
    $hypothesis.querySelector(".outcome").textContent = "";
  }
});

$status.innerHTML = "";