import { Marked } from "https://cdn.jsdelivr.net/npm/marked@13/+esm";
import hljs from "https://cdn.jsdelivr.net/npm/highlight.js@11/+esm";
import { parse } from "https://cdn.jsdelivr.net/npm/partial-json@0.1.7/+esm";
import { LLMClient, CONFIG } from "./llm-client.js";

// DOM elements
const elements = {
  demos: document.getElementById("demos"),
  hypotheses: document.getElementById("hypotheses"),
  hypothesisPrompt: document.getElementById("hypothesis-prompt"),
  synthesis: document.getElementById("synthesis"),
  synthesisResult: document.getElementById("synthesis-result"),
  status: document.getElementById("status"),
  filePath: document.getElementById("file-path"),
  loadFile: document.getElementById("load-file"),
};

// Configuration
const config = {
  loading: `<div class="text-center my-5"><div class="spinner-border" role="status"></div></div>`,
  statusTimeout: 3000,
  defaults: {
    apiBaseUrl: "https://llmfoundry.straive.com/openai/v1",
    apiKey: "",
    modelName: "gpt-4.1-nano"
  }
};

// Global state
let sessionId, description, hypotheses, llmClient;

// Setup marked
const marked = new Marked();
marked.use({
  renderer: {
    table: (header, body) => `<table class="table table-sm">${header}${body}</table>`,
    code: (code, lang) => {
      const language = hljs.getLanguage(lang) ? lang : "plaintext";
      return `<pre class="hljs language-${language}"><code>${hljs.highlight(code, { language }).value.trim()}</code></pre>`;
    },
  },
});

// Utility functions
const showStatus = (html, isError = false, timeout = config.statusTimeout) => {
  elements.status.innerHTML = html;
  if (timeout > 0) setTimeout(() => elements.status.innerHTML = "", timeout);
};

const getSettings = () => {
  const stored = localStorage.getItem("hypoforge-settings");
  return stored ? { ...config.defaults, ...JSON.parse(stored) } : config.defaults;
};

const saveSettings = (settings) => {
  localStorage.setItem("hypoforge-settings", JSON.stringify(settings));
};

const validateSettings = () => {
  const settings = getSettings();
  if (!settings.apiKey) {
    showStatus(`<div class="alert alert-warning">
      <i class="bi bi-exclamation-triangle"></i>
      Please configure your API settings by clicking the Settings button in the navigation.
    </div>`, false, 0);
    
    new bootstrap.Modal(document.getElementById('settingsModal')).show();
    return false;
  }
  
  // Initialize LLM client with current settings
  llmClient = new LLMClient(settings.apiBaseUrl, settings.apiKey, settings.modelName);
  return true;
};

// API functions
const apiCall = async (endpoint, options = {}) => {
  const response = await fetch(endpoint, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'API call failed');
  }
  
  return response.json();
};



// Data loading functions
const loadDataSource = async (source) => {
  const response = await apiCall('/load-data', {
    method: 'POST',
    body: JSON.stringify({ source })
  });
  return response;
};

const generateHypotheses = async (systemPrompt, description) => {
  elements.hypotheses.innerHTML = config.loading;
  
  try {
    for await (const content of llmClient.streamCompletion(
      systemPrompt, 
      description,
      { useSchema: true, jsonSchema: CONFIG.jsonSchema }
    )) {
      try {
        ({ hypotheses } = parse(content));
        drawHypotheses();
      } catch (e) {
        // Continue parsing as content streams
      }
    }
  } catch (error) {
    elements.hypotheses.innerHTML = `<div class="alert alert-danger">Error generating hypotheses: ${error.message}</div>`;
  }
};

const processDataLoad = async (source, audiencePrompt = null) => {
  if (!validateSettings()) return;

  elements.status.innerHTML = config.loading;
  
  try {
    const result = await loadDataSource(source);
    sessionId = result.session_id;
    description = result.description;
    
    showStatus(`<div class="alert alert-success">Loaded ${result.row_count} rows, ${result.column_count} columns</div>`);
    
    const systemPrompt = audiencePrompt || "You are an expert data analyst. Generate hypotheses that would be valuable to test on this dataset. Each hypothesis should be clear, specific, and testable.";
    elements.hypothesisPrompt.value = systemPrompt;
    
    await generateHypotheses(systemPrompt, description);
    elements.synthesis.classList.remove("d-none");
  } catch (error) {
    showStatus(`<div class="alert alert-danger">${error.message}</div>`, true, 5000);
  }
};

// UI functions
const drawHypotheses = () => {
  if (!Array.isArray(hypotheses)) return;
  elements.hypotheses.innerHTML = hypotheses
    .map(({ hypothesis, benefit }, index) => `
      <div class="hypothesis col py-3" data-index="${index}">
        <div class="card h-100">
          <div class="card-body">
            <h5 class="card-title hypothesis-title">${hypothesis}</h5>
            <p class="card-text hypothesis-benefit">${benefit}</p>
          </div>
          <div class="card-footer">
            <div class="result">
              <button type="button" class="btn btn-sm btn-primary test-hypothesis" data-index="${index}">Test</button>
            </div>
            <div class="outcome"></div>
          </div>
        </div>
      </div>
    `)
    .join("");
};

const initSettings = () => {
  const settings = getSettings();
  document.getElementById("apiBaseUrl").value = settings.apiBaseUrl;
  document.getElementById("apiKey").value = settings.apiKey;
  document.getElementById("modelName").value = settings.modelName;
};

// Event handlers
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
  
  // Reinitialize LLM client with new settings
  llmClient = new LLMClient(settings.apiBaseUrl, settings.apiKey, settings.modelName);
  
  bootstrap.Modal.getInstance(document.getElementById('settingsModal')).hide();
  elements.status.innerHTML = "";
  showStatus(`<div class="alert alert-success"><i class="bi bi-check-circle"></i> Settings saved successfully!</div>`);
});

// File path load
elements.loadFile.addEventListener("click", () => {
  const filePath = elements.filePath.value.trim();
  if (!filePath) {
    showStatus(`<div class="alert alert-warning">Please enter a file path</div>`);
    return;
  }
  processDataLoad(filePath);
});

elements.filePath.addEventListener("keypress", (e) => {
  if (e.key === "Enter") elements.loadFile.click();
});

// Demo selection
elements.demos.addEventListener("click", async (e) => {
  e.preventDefault();
  const demo = e.target.closest(".demo");
  if (!demo) return;
  
  const demoData = demos[+demo.dataset.index];
  await processDataLoad(demoData.href, demoData.audience);
});

// Hypothesis testing
elements.hypotheses.addEventListener("click", async (e) => {
  const button = e.target.closest(".test-hypothesis");
  if (!button || !validateSettings()) return;
  
  const index = button.dataset.index;
  const hypothesis = hypotheses[index];
  const analysisPrompt = document.getElementById("analysis-prompt").value || CONFIG.prompts.analysisDefault;

  const resultContainer = button.closest(".card");
  const result = resultContainer.querySelector(".result");
  const outcome = resultContainer.querySelector(".outcome");
  
  outcome.innerHTML = config.loading;
  
  try {
    // Step 1: Generate analysis code using LLM
    let fullAnalysis = "";
    for await (const content of llmClient.streamCompletion(
      analysisPrompt,
      `Hypothesis: ${hypothesis.hypothesis}\n\n${description}`
    )) {
      fullAnalysis = content;
      result.innerHTML = marked.parse(content);
    }

    // Step 2: Execute the code on the backend
    const codeExecutionResponse = await apiCall('/execute-hypothesis-test', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        analysis_code: fullAnalysis
      })
    });

    // Step 3: Generate summary using LLM
    const summaryUserContent = `Hypothesis: ${hypothesis.hypothesis}\n\n${description}\n\nResult: ${codeExecutionResponse.success}. p-value: ${codeExecutionResponse.p_value.toFixed(6)}`;
    
    for await (const summaryContent of llmClient.streamCompletion(
      CONFIG.prompts.summarySystem,
      summaryUserContent
    )) {
      outcome.classList.add(codeExecutionResponse.p_value < 0.05 ? "success" : "failure");
      outcome.innerHTML = marked.parse(summaryContent);
      result.innerHTML = `<details>
        <summary class="h5 my-3">Analysis</summary>
        ${marked.parse(fullAnalysis)}
      </details>`;
    }
  } catch (error) {
    outcome.innerHTML = `<pre class="alert alert-danger">${error.message}</pre>`;
  }
});

// Batch operations
document.querySelector("#run-all").addEventListener("click", () => {
  const pendingTests = [...document.querySelectorAll(".hypothesis")]
    .filter(h => !h.querySelector(".outcome").textContent.trim());
  pendingTests.forEach(el => el.querySelector(".test-hypothesis").click());
});

document.querySelector("#synthesize").addEventListener("click", async () => {
  if (!validateSettings()) return;
  
  const testedHypotheses = [...document.querySelectorAll(".hypothesis")]
    .map(h => ({
      title: h.querySelector(".hypothesis-title").textContent,
      benefit: h.querySelector(".hypothesis-benefit").textContent,
      outcome: h.querySelector(".outcome").textContent.trim(),
    }))
    .filter(d => d.outcome);

  elements.synthesisResult.innerHTML = config.loading;
  
  try {
    const userContent = testedHypotheses
      .map(h => `Hypothesis: ${h.title}\nBenefit: ${h.benefit}\nResult: ${h.outcome}`)
      .join('\n\n');
    
    for await (const content of llmClient.streamCompletion(
      CONFIG.prompts.synthesisSystem,
      userContent
    )) {
      elements.synthesisResult.innerHTML = marked.parse(content);
    }
  } catch (error) {
    elements.synthesisResult.innerHTML = `<div class="alert alert-danger">Error synthesizing results: ${error.message}</div>`;
  }
});

document.querySelector("#reset").addEventListener("click", () => {
  document.querySelectorAll(".hypothesis").forEach(hypothesis => {
    const index = hypothesis.dataset.index;
    hypothesis.querySelector(".result").innerHTML = 
      `<button type="button" class="btn btn-sm btn-primary test-hypothesis" data-index="${index}">Test</button>`;
    hypothesis.querySelector(".outcome").textContent = "";
    hypothesis.querySelector(".outcome").className = "outcome";
  });
});

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  initSettings();
  
  // Auto-show settings modal if no API key is stored
  const settings = getSettings();
  if (!settings.apiKey) {
    new bootstrap.Modal(document.getElementById('settingsModal')).show();
  }
});

// Load and render demos
elements.status.innerHTML = config.loading;
const { demos } = await apiCall('/config');

elements.demos.innerHTML = demos
  .map(({ title, body }, index) => `
    <div class="col py-3">
      <a class="demo card h-100 text-decoration-none" href="#" data-index="${index}">
        <div class="card-body">
          <h5 class="card-title">${title}</h5>
          <p class="card-text">${body}</p>
        </div>
      </a>
    </div>
  `)
  .join("");

elements.status.innerHTML = "";