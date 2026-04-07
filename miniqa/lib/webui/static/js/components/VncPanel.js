import {computed, defineComponent, onMounted, onUnmounted, ref, watch,} from 'vue';
import {rfbRef, state} from '../state.js';
import {send} from '../api.js';
import {initVncOverlay, startVnc} from '../vnc.js';
import {Icon} from './Icon.js';
import {RefsPanel} from './RefsPanel.js';

export const VncPanel = defineComponent({
  name: 'VncPanel',
  components: { Icon, RefsPanel },

  setup() {
    const screenEl  = ref(null);
    const overlayEl = ref(null);
    let   cleanupOverlay = null;

    const status   = computed(() => state.edit.worker_status);
    const progress = computed(() => state.edit.worker_progress);
    const message  = computed(() => state.edit.worker_message);

    const showLoading   = computed(() => !['ready', 'running'].includes(status.value));
    const showContainer = computed(() => ['ready', 'running'].includes(status.value));

    const loadingText = computed(() => {
      switch (status.value) {
        case 'stopped':
          return 'VM not started. Run a test to boot.';
        case 'booting':
          return 'Booting VM…';
        case 'loading_snapshot': {
          const [done, total] = progress.value ?? [0, 1];
          return message.value
            ? `Running: ${message.value}`
            : `Building required snapshot… (${Math.round(done / total * 100)} %)`;
        }
        case 'error':
          return `Error: ${message.value || 'Unknown error'}`;
        default:
          return 'VM stopped.';
      }
    });

    const showProgress  = computed(() => status.value === 'loading_snapshot');
    const showCancelPrep= computed(() => ['booting', 'loading_snapshot'].includes(status.value));

    const progressPct = computed(() => {
      const [done, total] = progress.value ?? [0, 1];
      return total > 0 ? Math.round((done / total) * 100) : 0;
    });
    const progressLabel = computed(() => {
      const [done, total] = progress.value ?? [0, 0];
      return `${done}/${total} steps`;
    });

    function cancelPrep() { send('cancel_prepare', {}); }

    // -- VNC connection ----------------------------------------------------

    // Wire mouse overlay interactions once on mount.
    // The overlay element exists in the DOM from the start (inside v-show, not v-if),
    // so we can safely attach listeners immediately.
    onMounted(() => {
      if (overlayEl.value) {
        cleanupOverlay = initVncOverlay(overlayEl.value);
      }
    });

    // Start noVNC connection when the container becomes visible (worker ready/running).
    watch(showContainer, async (visible) => {
      if (visible && !rfbRef.get()) {
        await startVnc(screenEl.value);
      }
    });

    onUnmounted(() => {
      cleanupOverlay?.();
      cleanupOverlay = null;
    });

    return {
      screenEl, overlayEl,
      status, showLoading, showContainer,
      loadingText, showProgress, showCancelPrep,
      progressPct, progressLabel, cancelPrep,
    };
  },

  template: `
    <div id="vnc-panel">

      <!-- Loading / error overlay -->
      <div id="vnc-loading" class="vnc-loading" v-show="showLoading">
        <div class="vnc-loading-inner">
          <div class="spinner"></div>
          <p id="vnc-loading-text">{{ loadingText }}</p>

          <div id="vnc-progress-bar-wrap" v-show="showProgress">
            <div
              id="vnc-progress-bar"
              :style="{ '--progress': progressPct + '%' }"
            ></div>
            <span id="vnc-progress-label">{{ progressLabel }}</span>
          </div>

          <button
            v-show="showCancelPrep"
            class="btn-ghost btn-sm"
            @click="cancelPrep"
          >Cancel</button>
        </div>
      </div>

      <!-- VNC screen (shown when worker is ready/running) -->
      <div id="vnc-container" v-show="showContainer">
        <div id="vnc-screen" ref="screenEl"></div>
        <div id="vnc-overlay" ref="overlayEl"></div>
        <div id="tool-hints">
          <span><kbd>Click</kbd> position</span>
          <span><kbd>⇧ Click</kbd> color</span>
          <span><kbd>Drag</kbd> region</span>
          <span><kbd>⇧ Drag</kbd> dom. color</span>
        </div>
      </div>

      <!-- Reference screenshots panel -->
      <RefsPanel />
    </div>`,
});
