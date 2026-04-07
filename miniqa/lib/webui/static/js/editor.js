/**
 * editor.js — Ace Editor lifecycle management.
 *
 * initEditor() creates/replaces the editor in the given DOM container.
 * The editor instance is stored in editorRef (state.js) so other modules
 * can access it without coupling through Vue props.
 */

import {editorRef, state} from './state.js';
import {escHtml} from './utils.js';
import {getSchemaOptions} from './schema.js';
import {onApiEvent} from './api.js';


// -- Initialise ----------------------------------------------------------------

/**
 * Create (or re-create) an Ace editor inside `container`.
 * `onChange` is called with the new YAML string on every content change.
 * `onScrollChange` is called when the editor scrolls (for step-status overlay).
 */
export function initEditor(container, initialYaml, onChange, onScrollChange) {
  // Destroy previous instance if present
  const prev = editorRef.get();
  if (prev) {
    prev.destroy();
    editorRef.clear();
  }
  container.innerHTML = '';

  const isDark  = document.documentElement.getAttribute('data-theme') === 'dark';
  const editor  = ace.edit(container, {
    mode:                      'ace/mode/yaml',
    theme:                     isDark ? 'ace/theme/tomorrow_night_bright' : 'ace/theme/chrome',
    tabSize:                   2,
    useSoftTabs:               true,
    showPrintMargin:           false,
    fontSize:                  13,
    fontFamily:                'var(--font-mono)',
    wrap:                      false,
    useWorker:                 false,
    enableBasicAutocompletion: true,
    enableLiveAutocompletion:  true,
    enableSnippets:            false,
  });

  editor.setValue(initialYaml, -1);
  editor.clearSelection();
  editor.completers = [yamlSchemaCompleter];

  editor.session.on('change', () => {
    const yaml = editor.getValue();
    if (onChange) onChange(yaml);
    _lintYaml(editor);
  });

  editor.session.on('changeScrollTop', () => {
    if (onScrollChange) onScrollChange();
  });

  editorRef.set(editor);
  return editor;
}

// -- Linting -------------------------------------------------------------------

function _lintYaml(editor) {
  if (typeof jsyaml === 'undefined') return;
  const text = editor.getValue();
  if (!text.trim()) { editor.session.setAnnotations([]); return; }
  try {
    jsyaml.loadAll(text);
    editor.session.setAnnotations([]);
  } catch (e) {
    editor.session.setAnnotations([{
      row:    e.mark?.line   ?? 0,
      column: e.mark?.column ?? 0,
      text:   e.message,
      type:   'error',
    }]);
  }
}

// -- Theme sync ----------------------------------------------------------------

export function syncEditorTheme() {
  const ed = editorRef.get();
  if (!ed) return;
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  ed.setTheme(isDark ? 'ace/theme/tomorrow_night_bright' : 'ace/theme/chrome');
}

// -- Insert text at caret / copy to clipboard ----------------------------------

export function insertOrCopy(value) {
  const ed = editorRef.get();
  if (!ed) {
    navigator.clipboard.writeText(value).catch(() => prompt('Copy this value:', value));
    return;
  }
  ed.session.insert(ed.getCursorPosition(), value);
  ed.focus();
}

// Wire screenshot-name insertion into the editor caret on backend events.
onApiEvent("insert_or_copy", (text) => insertOrCopy(text));

// -- Schema-based YAML completer -----------------------------------------------

const yamlSchemaCompleter = {
  getCompletions(editor, session, pos, prefix, callback) {
    if (!state.schema) { callback(null, []); return; }

    const curLine   = session.getLine(pos.row);
    const curIndent = curLine.match(/^(\s*)/)[1].length;

    // Walk upward building the key path, handling "- " list boundaries
    const path = [];
    let targetIndent = curIndent;

    for (let row = pos.row - 1; row >= 0 && targetIndent > 0; row--) {
      const line = session.getLine(row);
      if (line.trim() === '' || line.trim().startsWith('#')) continue;
      const ind = line.match(/^(\s*)/)[1].length;
      if (ind >= targetIndent) continue;

      const trimmed = line.trim();
      const isList  = /^-\s/.test(trimmed) || trimmed === '-';
      const key     = trimmed.replace(/^-\s+/, '').replace(/:.*$/, '').trim();

      if (isList) {
        const effectiveContent = ind + 2;
        if (targetIndent > effectiveContent) {
          if (key) path.unshift(key);
          targetIndent = effectiveContent;
        } else {
          targetIndent = ind;
        }
      } else {
        if (key) path.unshift(key);
        targetIndent = ind;
      }
    }

    // Collect sibling keys already present at the current level
    const existingProps = [];
    let   targetInd     = -1;
    for (let row = pos.row - 1; row >= 0; row--) {
      const line    = session.getLine(row);
      if (line.trim() === '' || line.trim().startsWith('#')) continue;
      const realInd = line.match(/^(\s*)/)[1].length;
      let   ind     = realInd;
      if (/^-\s+/.test(line.trim())) ind += 2;
      if (targetInd === -1) targetInd = ind;
      if (ind < targetInd) break;
      if (ind > targetInd) continue;
      const key = line.trim().replace(/^-\s+/, '').replace(/:.*$/, '').trim();
      if (key && !existingProps.includes(key)) existingProps.push(key);
      if (realInd < targetInd) break;
    }

    const options     = getSchemaOptions(state.schema, path, existingProps);
    const completions = options
      .filter(o => !existingProps.includes(o.key))
      .map(o => ({
        caption:  o.key,
        value:    o.isObject ? `${o.key}:\n  ` : `${o.key}: `,
        meta:     o.type || 'key',
        docHTML:  o.description ? `<b>${o.key}</b><br>${escHtml(o.description)}` : undefined,
        score:    1000,
      }));

    callback(null, completions);
  },
};
