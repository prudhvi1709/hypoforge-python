/**
 * LLM Client Module
 * Handles direct communication with LLM APIs from the browser
 */

export class LLMClient {
  constructor(apiBaseUrl, apiKey, modelName) {
    this.apiBaseUrl = apiBaseUrl;
    this.apiKey = apiKey;
    this.modelName = modelName;
    this.defaultTemperature = 0;
  }

  /**
   * Stream completion from LLM API
   * @param {string} systemPrompt - System prompt
   * @param {string} userContent - User content
   * @param {object} options - Additional options
   * @returns {AsyncGenerator} - Streaming response
   */
  async* streamCompletion(systemPrompt, userContent, options = {}) {
    const body = {
      model: this.modelName,
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: userContent },
      ],
      stream: true,
      stream_options: { include_usage: true },
      temperature: options.temperature ?? this.defaultTemperature,
    };

    if (options.useSchema && options.jsonSchema) {
      body.response_format = {
        type: "json_schema",
        json_schema: options.jsonSchema
      };
    }

    const response = await fetch(`${this.apiBaseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.apiKey}:hypoforge`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body)
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`LLM API error (${response.status}): ${error}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullContent = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.trim().startsWith('data: ')) {
          const dataStr = line.slice(6);
          if (dataStr && dataStr !== '[DONE]') {
            try {
              const data = JSON.parse(dataStr);
              const choices = data.choices || [];
              if (choices.length > 0) {
                const delta = choices[0].delta || {};
                if (delta.content) {
                  fullContent += delta.content;
                  yield fullContent;
                }
              }
            } catch (e) {
              // Skip invalid JSON lines
            }
          }
        }
      }
    }
  }

  /**
   * Get complete response (non-streaming)
   * @param {string} systemPrompt - System prompt
   * @param {string} userContent - User content
   * @param {object} options - Additional options
   * @returns {Promise<string>} - Complete response
   */
  async getCompletion(systemPrompt, userContent, options = {}) {
    let lastContent = "";
    for await (const content of this.streamCompletion(systemPrompt, userContent, options)) {
      lastContent = content;
    }
    return lastContent;
  }
}

/**
 * Configuration and prompts
 */
export const CONFIG = {
  prompts: {
    hypothesisDefault: "You are an expert data analyst. Generate hypotheses that would be valuable to test on this dataset. Each hypothesis should be clear, specific, and testable.",
    
    analysisDefault: `You are an expert data scientist. Given a hypothesis and dataset description, write Python code to test this hypothesis using appropriate statistical methods.

CRITICAL: Your code must follow this exact pattern:

\`\`\`python
import pandas as pd
import scipy.stats as stats
import numpy as np

def test_hypothesis(df):
    # Your analysis code here
    # Use appropriate statistical tests (t-test, chi-square, correlation, etc.)
    # Calculate p-value
    # Return (is_significant, p_value) where is_significant is boolean
    
    # Example:
    # statistic, p_value = stats.ttest_ind(group1, group2)
    # return p_value < 0.05, p_value
    
    pass
\`\`\`

Use the most appropriate statistical test based on the hypothesis and data types. Always return exactly (boolean, float).`,

    summarySystem: `You are an expert data analyst.
Given a hypothesis and its outcome, provide a plain English summary of the findings as a crisp H5 heading (#####), followed by 1-2 concise supporting sentences.
Highlight in **bold** the keywords in the supporting statements.
Do not mention the p-value but _interpret_ it to support the conclusion quantitatively.`,

    synthesisSystem: `Given the below hypotheses and results, summarize the key takeaways and actions in Markdown.
Begin with the hypotheses with lowest p-values AND highest business impact. Ignore results with errors.
Use action titles has H5 (#####). Just reading titles should tell the audience EXACTLY what to do.
Below each, add supporting bullet points that
  - PROVE the action title, mentioning which hypotheses led to this conclusion.
  - Do not mention the p-value but _interpret_ it to support the action
  - Highlight key phrases in **bold**.
Finally, after a break (---) add a 1-paragraph executive summary section (H5) summarizing these actions.`
  },

  jsonSchema: {
    name: "HypothesesResponse",
    schema: {
      type: "object",
      required: ["hypotheses"],
      properties: {
        hypotheses: {
          type: "array",
          items: {
            type: "object",
            required: ["hypothesis", "benefit"],
            properties: {
              hypothesis: { type: "string" },
              benefit: { type: "string" }
            }
          }
        }
      }
    }
  }
}; 