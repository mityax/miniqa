import {computed, defineComponent, onMounted, watch} from 'vue';
import {state} from './state.js';
import {initWs} from './api.js';
import {loadSchema} from './schema.js';
import {Icon} from './components/Icon.js';
import {PipelineView} from './components/PipelineView.js';
import {EditView} from './components/EditView.js';
import {ToastContainer} from './components/ToastContainer.js';
import {Lightbox} from './components/Lightbox.js';
import {DiffModal} from './components/modals/DiffModal.js';
import {PromptModal} from './components/modals/PromptModal.js';
import {SchemaErrorModal} from './components/modals/SchemaErrorModal.js';

export const App = defineComponent({
  name: 'App',

  components: {
    Icon, PipelineView, EditView,
    ToastContainer, Lightbox, DiffModal, PromptModal, SchemaErrorModal,
  },

  setup() {
    const showPipeline = computed(() => state.currentView === 'pipeline');
    const showEdit     = computed(() => state.currentView === 'edit');

    // Keep the <html data-theme> attribute in sync with state.theme
    watch(() => state.theme, (t) => {
      document.documentElement.setAttribute('data-theme', t);
    }, { immediate: true });

    // -- Open edit view ----------------------------------------------------

    function openEdit(stem) {
      if (state.currentView === 'edit' && state.edit.has_unsaved) {
        if (!confirm('You have unsaved changes. Leave without saving?')) return;
      }
      const t = state.tests.find(x => x.stem === stem);

      state.currentView             = 'edit';
      state.edit.test_stem          = stem;
      state.edit.yaml               = t?.yaml ?? '';
      state.edit.has_unsaved        = false;
      state.edit.current_step       = null;
      state.edit.step_results       = [];
      state.edit._popoverAutoOpened = false;
      state.stepPopover.visible     = false;
    }

    // -- Boot --------------------------------------------------------------

    onMounted(async () => {
      await loadSchema();
      initWs();
    });

    return { state, showPipeline, showEdit, openEdit };
  },

  template: `
    <!-- Tab conflict screen -->
    <div id="tab-conflict" class="overlay-screen" v-show="state._tabConflict">
      <div class="overlay-card">
        <Icon name="alert-triangle" :xl="true" />
        <h2>Already open</h2>
        <p>The webui is already open in another tab.<br>Close the other tab and reload.</p>
        <button @click="() => location.reload()">Reload</button>
      </div>
    </div>

    <!-- Main app (hidden during tab conflict) -->
    <div id="app" v-show="!state._tabConflict">
      <PipelineView v-show="showPipeline" @open-edit="openEdit" />
      <EditView     v-show="showEdit" />
    </div>

    <!-- Global overlays — always mounted, toggled via state -->
    <Lightbox />
    <DiffModal />
    <PromptModal />
    <SchemaErrorModal />
    <ToastContainer />`,
});
