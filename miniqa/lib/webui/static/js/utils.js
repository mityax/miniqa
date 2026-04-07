/**
 * utils.js — Pure utility functions
 *
 * No Vue imports, no DOM, no side-effects.  Safe to call anywhere.
 */

// -- HTML escaping -------------------------------------------------------------

export function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// -- Duration formatting -------------------------------------------------------

/** Format a duration (seconds), e.g. "1:23". */
export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '';

  const totalSeconds = Math.floor(seconds);
  const hrs = Math.floor(totalSeconds / 3600);
  const mins = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;

  if (hrs > 0) {
    return `${hrs}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  return `${mins}:${String(secs).padStart(2, '0')}`;
}

// -- YAML helpers --------------------------------------------------------------

/**
 * Parse the first document in the given YAML string using js-yaml.
 */
export function jsyamlParse(text) {
  return jsyaml.loadAll(text)[0];
}

/** Extract snapshot names produced by a parsed test case object. */
export function findSnapshots(tc) {
  if (!tc?.steps || !Array.isArray(tc.steps)) return [];
  return tc.steps
    .filter(s => s.snapshot)
    .map(s => s.snapshot);
}

// -- Pipeline validation -------------------------------------------------------

/**
 * Client-side pipeline validation — mirrors backend logic.
 * Returns an array of { scope, test_name?, message } error objects.
 */
export function validatePipeline(tests) {
  const errors = [];

  const tcs = tests.map(t => {
    try {
      const d = jsyamlParse(t.yaml);
      return { stem: t.stem, name: d?.name ?? t.stem, from: d?.from, snapshots: findSnapshots(d) };
    } catch { return null; }
  }).filter(Boolean);

  if (!tcs.length) return errors;

  // Build snapshot → provider map
  const allSnaps = {};
  tcs.forEach(t => t.snapshots.forEach(s => {
    (allSnaps[s] = allSnaps[s] ?? []).push(t.name);
  }));

  if (tcs.every(t => t.from)) {
    errors.push({ scope: 'global', message: "No test without a 'from' — no pipeline entry point." });
  }

  Object.entries(allSnaps).forEach(([snap, providers]) => {
    if (providers.length > 1) {
      providers.forEach(p =>
        errors.push({ scope: 'test', test_name: p,
          message: `Snapshot '${snap}' is also provided by: ${providers.filter(x => x !== p).join(', ')}` })
      );
    }
  });

  tcs.forEach(t => {
    if (t.from && !allSnaps[t.from])
      errors.push({ scope: 'test', test_name: t.name,
        message: `Required snapshot '${t.from}' not created by any test.` });
  });

  // Cycle detection (DFS)
  const hasCycle = (name, seen = new Set()) => {
    if (seen.has(name)) return true;
    const t = tcs.find(x => x.name === name);
    if (!t || !t.from) return false;
    const provider = tcs.find(x => x.snapshots.includes(t.from));
    return provider ? hasCycle(provider.name, new Set([...seen, name])) : false;
  };
  tcs.filter(t => hasCycle(t.name)).forEach(t =>
    errors.push({ scope: 'test', test_name: t.name, message: 'Circular snapshot dependency.' })
  );

  return errors;
}

// -- Test property derivation --------------------------------------------------

/** Derive display properties for a test given current pipeline state. */
export function computeTestProperties(t, pipeline) {
  const stem   = t.stem;
  const raw    = pipeline.statuses[stem];
  const status = (
    pipeline.running
      ? raw
      : (raw === 'started' ? 'canceled' : raw)
  ) || 'pending';

  const result   = pipeline.results[stem]       ?? null;
  const startTs  = pipeline.test_start_time[stem];
  const duration = status === "started" ?? (startTs ? (Date.now() / 1000 - startTs) : result?.duration ?? null);
  const curStep  = pipeline.current_steps[stem] ?? null;
  const failed   = result?.success === false;
  const succeeded= result?.success === true;

  return { stem, status, result, duration, curStep, failed, succeeded };
}

// -- Step description ----------------------------------------------------------

/**
 * Return an HTML string describing a single YAML step object.
 * Used for display in the test-item and edit-view step lists.
 */
export function describeStep(step, withDetails = true) {
  if (typeof step === 'string') return escHtml(step);
  const keys     = Object.keys(step || {});
  const stepType = keys[0];

  let res = stepType ? `<code>${escHtml(stepType)}</code>` : 'step';

  if (withDetails && stepType) {
    const details    = [];
    const stepValue  = step[stepType];

    try {
      if (typeof stepValue === 'string' || typeof stepValue === 'number') {
        details.push(`<b>${escHtml(JSON.stringify(stepValue))}</b>`);

      } else if (stepType === 'screenshot') {
        details.push(`<b>${escHtml(stepValue.name)}</b>`);

      } else if (stepType === 'wait' && typeof stepValue?.for === 'string') {
        details.push(`for <b>${escHtml(stepValue.for)}</b>`);

      } else if (stepType === 'wait' && typeof stepValue?.for?.dominant_color === 'string') {
        const col = escHtml(stepValue.for.dominant_color);
        let s = `for dominant color <b>${col}</b>`;
        if (stepValue.for.dominant_color.startsWith('#')) {
          s += ` <span style="width:1em;height:1em;display:inline-block;vertical-align:middle;background:${col}"></span>`;
        }
        details.push(s);

      } else if (stepType === 'wait' && typeof stepValue?.for?.find?.text === 'string') {
        details.push(`for text: <b>"${escHtml(stepValue.for.find.text)}"</b>`);

      } else if (stepType === 'touch') {
        if (stepValue.length === 1 && stepValue[0]?.position?.find) {
          for (let key in stepValue[0].position.find) {
            details.push(`${escHtml(key)}: <b>${escHtml(JSON.stringify(stepValue[0].position.find[key]))}</b>`)
          }
        } else if (Array.isArray(stepValue)) {
          details.push(`<b>${stepValue.length} touch point(s)</b>`);
        } else if (stepValue?.position?.find) {
          for (let key in stepValue.position.find) {
            details.push(`${escHtml(key)}: <b>${escHtml(JSON.stringify(stepValue[0].position.find[key]))}</b>`)
          }
        }

      } else if (stepType === 'mouse_move' && stepValue.find) {
        details.push(
          Object.keys(stepValue.find)
            .map(k => `<b>${escHtml(k)}:</b> ${escHtml(JSON.stringify(stepValue.find[k]))}`)
            .join(' ')
        );
      }

      if (stepValue && Array.isArray(stepValue.regions)) {
        details.push(`<b>${stepValue.regions.length} region(s)</b>`);
      }
      if (stepValue?.timeout) {
        const t = typeof stepValue.timeout === 'string'
          ? escHtml(stepValue.timeout)
          : `${stepValue.timeout}s`;
        details.push(`<b>timeout: ${t}</b>`);
      }

      if (details.length) res += ` <span class="step-details">${details.join(' &bull; ')}</span>`;
    } catch (e) {
      console.error('[describeStep]', step, e);
    }
  }

  return res;
}

// -- YAML step-line finder -----------------------------------------------------

/**
 * Scan YAML text and return 0-based line numbers for each step list-item
 * under the root-level `steps:` key.
 */
export function findStepLines(yamlText) {
  const lines     = yamlText.split('\n');
  const stepLines = [];
  let inSteps     = false;
  let stepsIndent = -1;

  for (let i = 0; i < lines.length; i++) {
    const line   = lines[i];
    if (line.trim() === '') continue;
    const indent = line.match(/^(\s*)/)[1].length;

    if (!inSteps) {
      if (/^steps\s*:/.test(line.trim()) && indent === 0) {
        inSteps     = true;
        stepsIndent = indent;
      }
    } else {
      if (indent <= stepsIndent && line.trim() !== '' && !/^steps\s*:/.test(line.trim())) break;
      if (/^\s*-\s/.test(line) && indent === stepsIndent + 2) stepLines.push(i);
    }
  }

  return stepLines;
}

// -- Clipboard -----------------------------------------------------------------

export async function copyToClipboard(text) {
  await navigator.clipboard.writeText(text);
}
