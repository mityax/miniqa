import {computed, defineComponent, ref, watch} from 'vue';
import {state} from '../state.js';
import {send} from '../api.js';
import {validatePipeline} from '../utils.js';
import {syncEditorTheme} from '../editor.js';
import {Icon} from './Icon.js';
import {TestItem} from './TestItem.js';
import {promptModal} from './modals/PromptModal.js';

export const PipelineView = defineComponent({
  name: 'PipelineView',
  components: { Icon, TestItem },

  emits: ['open-edit'],

  setup(_, { emit }) {

    // -- Validation errors ------------------------------------------------
    const validationErrors = computed(() => validatePipeline(state.tests));

    const runAllDisabled = computed(() =>
      validationErrors.value.length > 0 || state.pipeline.running
    );

    // -- Run-selected bar -------------------------------------------------
    const selectedCount = computed(() => state.selectedStems.length);

    function deselectAll() { state.selectedStems.splice(0); }

    function runSelected() {
      send('run_pipeline', { stems: [...state.selectedStems] });
      state.selectedStems.splice(0);
    }

    // -- Pipeline actions -------------------------------------------------
    function runAll() {
      send('run_pipeline', {});
      state.pipeline.running = true;
    }

    // Local ref so spinner only shows until pipeline_done resets pipeline.running
    const cancelling = ref(false);
    watch(() => state.pipeline.running, (running) => {
      if (!running) cancelling.value = false;
    });

    function cancelPipeline() {
      send('cancel_pipeline', {});
      cancelling.value = true;
    }

    // -- Add test ---------------------------------------------------------
    async function addTest() {
      const filename = await promptModal('New test file', 'Enter filename (without extension)', 'new_test');
      if (!filename) return;
      const defaultYaml = `name: ${filename}\nsteps:\n  - sleep: 1s\n`;
      state.tests.push({ stem: filename, filename: `${filename}.yml`, yaml: defaultYaml });
      emit('open-edit', filename);
    }

    // -- Theme toggle -----------------------------------------------------
    function toggleTheme() {
      const next = state.theme === 'dark' ? 'light' : 'dark';
      state.theme = next;
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      syncEditorTheme();
    }

    const themeIcon = computed(() => state.theme === 'dark' ? 'sun' : 'moon');

    return {
      state, validationErrors, runAllDisabled,
      selectedCount, deselectAll, runSelected,
      runAll, cancelPipeline, cancelling,
      addTest, toggleTheme, themeIcon,
    };
  },

  template: `
    <div id="view-pipeline" class="view">
      <header class="app-header">
        <div class="header-left">
          <Icon name="cpu" extra-class="icon-brand" />
          <h1>miniQA WebUI</h1>
        </div>
        <div class="header-right">
          <button class="btn-ghost" @click="addTest">
            <Icon name="plus" /> New test
          </button>
          <button
            class="btn-primary"
            :disabled="runAllDisabled"
            v-show="!state.pipeline.running"
            @click="runAll"
          >
            <Icon name="play" /> Run all
          </button>
          <button
            class="btn-danger"
            :disabled="cancelling"
            v-show="state.pipeline.running"
            @click="cancelPipeline"
          >
            <Icon :name="cancelling ? 'loader' : 'square'" :spin="cancelling" />
            {{ cancelling ? 'Cancelling…' : 'Stop' }}
          </button>
          <button class="btn-icon" title="Toggle theme" @click="toggleTheme">
            <Icon :name="themeIcon" />
          </button>
        </div>
      </header>

      <!-- Validation banner -->
      <div
        id="pipeline-errors"
        class="validation-banner"
        v-show="validationErrors.length"
      >
        <div
          v-for="(e, i) in validationErrors"
          :key="i"
          class="val-item"
        >
          <span class="val-scope">{{ e.scope === 'global' ? 'Global' : e.test_name }}</span>
          &nbsp;—&nbsp;{{ e.message }}
        </div>
      </div>

      <!-- Run-selected bar -->
      <div
        id="run-selected-bar"
        class="run-selected-bar"
        v-show="selectedCount > 0"
      >
        <span>{{ selectedCount }} test{{ selectedCount > 1 ? 's' : '' }} selected</span>
        <button class="btn-primary btn-sm" @click="runSelected">
          <Icon name="play" /> Run selected (and dependencies)
        </button>
        <button class="btn-ghost btn-sm" @click="deselectAll">Clear</button>
      </div>

      <!-- Test list -->
      <div id="test-list" class="test-list">
        <TestItem
          v-for="t in state.tests"
          :key="t.stem"
          :t="t"
          @open-edit="$emit('open-edit', $event)"
        />
      </div>
    </div>`,
});
