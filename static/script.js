import { Marked } from "https://cdn.jsdelivr.net/npm/marked@13/+esm";
import hljs from "https://cdn.jsdelivr.net/npm/highlight.js@11/+esm";
import { parse } from "https://cdn.jsdelivr.net/npm/partial-json@0.1.7/+esm";

const $demos = document.getElementById("demos");
const $hypotheses = document.getElementById("hypotheses");
const $hypothesisPrompt = document.getElementById("hypothesis-prompt");
const $synthesis = document.getElementById("synthesis");
const $synthesisResult = document.getElementById("synthesis-result");
const $status = document.getElementById("status");
const $filePath = document.getElementById("file-path");
const $loadFile = document.getElementById("load-file");
const loading = `<div class="text-center my-5"><div class="spinner-border" role="status"></div></div>`;

let sessionId;
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
    
    // Auto-show settings modal when credentials are missing
    const modal = new bootstrap.Modal(document.getElementById('settingsModal'));
    modal.show();
    
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
  
  // Show success message briefly
  $status.innerHTML = `<div class="alert alert-success">
    <i class="bi bi-check-circle"></i>
    Settings saved successfully!
  </div>`;
  setTimeout(() => $status.innerHTML = "", 3000);
});

// Initialize settings on page load
document.addEventListener("DOMContentLoaded", () => {
  initSettings();
  
  // Auto-show settings modal if no API key is stored
  const settings = getSettings();
  if (!settings.apiKey) {
    const modal = new bootstrap.Modal(document.getElementById('settingsModal'));
    modal.show();
  }
});

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

// Streaming API call function - replicates original asyncLLM pattern
async function streamFromBackend(endpoint, requestBody, onChunk) {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(requestBody)
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Streaming API call failed');
  }
  
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    
    const chunk = decoder.decode(value);
    const lines = chunk.split('\n');
    
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6));
          onChunk(data);
        } catch (e) {
          // Skip invalid JSON lines
        }
      }
    }
  }
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
    // Handle demo data - use the new /load-demo endpoint
    const response = await apiCall('/load-demo', {
      method: 'POST',
      body: JSON.stringify({ demo_url: source.href })
    });
    return response;
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
    sessionId = result.session_id;
    description = result.description;
    
    $status.innerHTML = `<div class="alert alert-success">Loaded ${result.row_count} rows, ${result.column_count} columns</div>`;
    setTimeout(() => $status.innerHTML = "", 3000);
    
    const systemPrompt = $hypothesisPrompt.value = "You are an expert data analyst. Generate hypotheses that would be valuable to test on this dataset. Each hypothesis should be clear, specific, and testable.";
    const settings = getSettings();
    
    $hypotheses.innerHTML = loading;
    
    // Use streaming for hypothesis generation
    await streamFromBackend('/generate-hypotheses', {
      system_prompt: systemPrompt,
      description: description,
      api_base_url: settings.apiBaseUrl,
      api_key: settings.apiKey,
      model_name: settings.modelName
    }, (data) => {
      if (data.content) {
        try {
          ({ hypotheses } = parse(data.content));
          drawHypotheses();
        } catch (e) {
          // Continue parsing as content streams
        }
      }
    });
    $synthesis.classList.remove("d-none");
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
    sessionId = result.session_id;
    description = result.description;
    
    $status.innerHTML = `<div class="alert alert-success">Loaded ${result.row_count} rows, ${result.column_count} columns</div>`;
    setTimeout(() => $status.innerHTML = "", 3000);
    
    const systemPrompt = $hypothesisPrompt.value = demo.audience;
    const settings = getSettings();
    
    $hypotheses.innerHTML = loading;
    
    // Use streaming for hypothesis generation
    await streamFromBackend('/generate-hypotheses', {
      system_prompt: systemPrompt,
      description: description,
      api_base_url: settings.apiBaseUrl,
      api_key: settings.apiKey,
      model_name: settings.modelName
    }, (data) => {
      if (data.content) {
        try {
          ({ hypotheses } = parse(data.content));
          drawHypotheses();
        } catch (e) {
          // Continue parsing as content streams
        }
      }
    });
    $synthesis.classList.remove("d-none");
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
    let fullAnalysis = "";
    let testResult = null;
    
    // Use streaming for hypothesis testing with session ID
    await streamFromBackend('/test-hypothesis', {
      hypothesis: hypothesis.hypothesis,
      session_id: sessionId,
      analysis_prompt: analysisPrompt,
      api_base_url: settings.apiBaseUrl,
      api_key: settings.apiKey,
      model_name: settings.modelName
    }, (data) => {
      if (data.type === 'analysis') {
        fullAnalysis = data.content;
        $result.innerHTML = marked.parse(data.content);
      } else if (data.type === 'summary') {
        testResult = data;
        $outcome.classList.add(data.p_value < 0.05 ? "success" : "failure");
        $outcome.innerHTML = marked.parse(data.content);
        $result.innerHTML = `<details>
          <summary class="h5 my-3">Analysis</summary>
          ${marked.parse(fullAnalysis)}
        </details>`;
      }
    });
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
    
    // Use streaming for synthesis
    await streamFromBackend('/synthesize', {
      hypotheses,
      api_base_url: settings.apiBaseUrl,
      api_key: settings.apiKey,
      model_name: settings.modelName
    }, (data) => {
      if (data.content) {
        $synthesisResult.innerHTML = marked.parse(data.content);
      }
    });
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