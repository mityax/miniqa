import {computed, defineComponent, nextTick, onMounted, onUnmounted, ref, watch} from 'vue';
import {state} from '../state.js';
import {onApiEvent, send, toast} from '../api.js';
import {initEditor, syncEditorTheme} from '../editor.js';
import {stopVnc} from '../vnc.js';
import {jsyamlParse} from '../utils.js';
import {validateAgainstSchema} from '../schema.js';
import {promptModal} from './modals/PromptModal.js';
import {showSchemaErrorModal} from './modals/SchemaErrorModal.js';
import {Icon} from './Icon.js';
import {StepStatusBar} from './StepStatusBar.js';
import {VncPanel} from './VncPanel.js';

export const EditView = defineComponent({
  name: 'EditView',
  components: { Icon, StepStatusBar, VncPanel },
  emits: ['back'],

  setup(_, { emit }) {
    const editorContainer = ref(null);
    const statusBarRef    = ref(null);
    const runResult       = ref(null);
    const cancelling      = ref(false);

    // -- Run-result display ------------------------------------------------

    const runResultVisible = computed(() => runResult.value !== null);

    const runResultClass = computed(() => [
      'run-result',
      runResult.value ? (runResult.value.success ? 'success' : 'failed') : '',
    ].join(' '));

    const runResultText = computed(() => {
      const r = runResult.value;
      if (!r) return '';
      if (r.success) return '✓ Test passed';
      return [
        `✗ Test failed at step ${(r.failed_step ?? 0) + 1}`,
        r.message       ? `Message: ${r.message}`                                : null,
        r.exception_msg ? `Exception (${r.exception_type}): ${r.exception_msg}` : null,
      ].filter(Boolean).join('\n');
    });

    // -- Worker / button state ---------------------------------------------

    const workerStatus  = computed(() => state.edit.worker_status);
    const runDisabled   = computed(() =>
      ['booting', 'loading_snapshot', 'running'].includes(workerStatus.value)
    );
    const showCancelRun = computed(() => workerStatus.value === 'running');

    watch(workerStatus, (s) => { if (s !== 'running') cancelling.value = false; });

    // -- Editor lifecycle -------------------------------------------------
    // Only (re)mount Ace after a test stem is set AND the container is visible.
    // Ace needs a visible container to compute gutter/line-height correctly.

    function mountEditor() {
      const container = editorContainer.value;
      if (!container || !state.edit.test_stem) return;

      initEditor(
        container,
        state.edit.yaml,
        (yaml) => {
          state.edit.yaml = yaml;
          const original = state.tests.find(x => x.stem === state.edit.test_stem)?.yaml ?? '';
          state.edit.has_unsaved = yaml !== original;
        },
        () => statusBarRef.value?.refresh?.(),
      );
    }

    // Re-mount when the user opens a different test
    watch(() => state.edit.test_stem, async (stem) => {
      if (!stem) return;
      await nextTick();
      mountEditor();
    });

    // Also mount if we arrive at the edit view with a stem already set
    // (e.g. on reconnect, or if App sets currentView before this component
    // has had a chance to run its stem-watcher)
    watch(() => state.currentView, async (view) => {
      if (view === 'edit' && state.edit.test_stem) {
        await nextTick();
        mountEditor();
      }
    });

    // -- Event bus --------------------------------------------------------

    const _unsubs = [];
    onMounted(() => {
      _unsubs.push(
        onApiEvent('run_result', (result) => { runResult.value = result; }),
        onApiEvent('open_popover', (stepIdx) => { statusBarRef.value?.openPopover?.(stepIdx); }),
      );
      document.addEventListener('keydown', _onKeydown);
    });
    onUnmounted(() => {
      _unsubs.forEach(fn => fn());
      document.removeEventListener('keydown', _onKeydown);
    });

    function _onKeydown(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 's' && state.currentView === 'edit') {
        e.preventDefault();
        if (state.edit.has_unsaved)
          send('save_test', { stem: state.edit.test_stem, yaml: state.edit.yaml });
      }
    }

    // -- Toolbar actions ---------------------------------------------------

    function goBack() {
      if (state.edit.has_unsaved && !confirm('You have unsaved changes. Leave without saving?'))
        return;
      state.currentView         = 'pipeline';
      state.stepPopover.visible = false;
      runResult.value           = null;
      stopVnc();
      emit('back');
    }

    async function save() {
      const doSave = () =>
        send('save_test', { stem: state.edit.test_stem, yaml: state.edit.yaml });

      if (state.schema && typeof jsyaml !== 'undefined') {
        let parsed;
        try { parsed = jsyamlParse(state.edit.yaml); } catch { doSave(); return; }
        const errors = await validateAgainstSchema(parsed);
        if (errors.length) { showSchemaErrorModal(errors, doSave); return; }
      }
      doSave();
    }

    async function createScreenshot() {
      if (!['ready', 'running'].includes(workerStatus.value)) {
        toast('VM is not running', 'error'); return;
      }
      const name = await promptModal(
        'Reference screenshot',
        'Enter a name for this screenshot (no file extension)',
        `${state.edit.test_stem}/my_screenshot`,
      );
      if (!name) return;
      send('create_screenshot', { name });
    }

    function runTest() {
      state.edit._popoverAutoOpened = false;
      state.edit.step_results       = [];
      state.edit.current_step       = null;
      state.stepPopover.visible     = false;
      runResult.value               = null;
      send('prepare_worker', { stem: state.edit.test_stem });
      state._runAfterPrepare        = true;
    }

    function cancelRun() {
      send('cancel_edit_run', {});
      cancelling.value = true;
    }

    // -- Theme -------------------------------------------------------------



    function toggleTheme() {
      const next = state.theme === 'dark' ? 'light' : 'dark';
      state.theme = next;
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      syncEditorTheme();
    }

    const themeIcon = computed(() => state.theme === 'dark' ? 'sun' : 'moon');

    return {
      state, editorContainer, statusBarRef,
      runResult, runResultVisible, runResultClass, runResultText,
      runDisabled, showCancelRun, cancelling,
      goBack, save, createScreenshot, runTest, cancelRun,
      toggleTheme, themeIcon,
    };
  },

  template: `
    <div id="view-edit" class="view">
      <header class="app-header">
        <div class="header-left">
          <button class="btn-icon" title="Back" @click="goBack">
            <Icon name="arrow-left" />
          </button>
          <h2>{{ state.edit.test_stem }}</h2>
          <span
            class="unsaved-dot"
            v-show="state.edit.has_unsaved"
            title="Unsaved changes"
          ></span>
        </div>
        <div class="header-right">
          <button
            class="btn-ghost"
            :disabled="!state.edit.has_unsaved"
            @click="save"
          >
            <Icon name="save" /> Save
          </button>
          <button class="btn-ghost" @click="createScreenshot">
            <Icon name="camera" /> Screenshot
          </button>
          <div class="btn-group">
            <button
              v-show="showCancelRun"
              class="btn-ghost"
              :disabled="cancelling"
              @click="cancelRun"
            >
              <Icon :name="cancelling ? 'loader' : 'x'" :spin="cancelling" />
              {{ cancelling ? 'Cancelling\u2026' : 'Cancel' }}
            </button>
            <button
              class="btn-primary"
              :disabled="runDisabled"
              @click="runTest"
            >
              <Icon name="play" /> Run test
            </button>
          </div>
          <button class="btn-icon" title="Toggle theme" @click="toggleTheme">
            <Icon :name="themeIcon" />
          </button>
        </div>
      </header>

      <div id="edit-layout">
        <StepStatusBar ref="statusBarRef" />

        <div id="editor-panel">
          <div id="yaml-editor" ref="editorContainer"></div>
          <div
            id="run-result"
            :class="runResultClass"
            v-show="runResultVisible"
            style="white-space:pre-line"
          >{{ runResultText }}</div>
        </div>

        <VncPanel />
      </div>
    </div>`,
});
