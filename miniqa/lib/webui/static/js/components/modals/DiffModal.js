import {defineComponent, ref, watch} from 'vue';
import {state} from '../../state.js';
import {send} from '../../api.js';
import {Icon} from '../Icon.js';
import {RegionOverlay} from "../RegionOverlay.js";

export const DiffModal = defineComponent({
  name: 'DiffModal',
  components: { Icon, RegionOverlay },

  setup() {
    const sliderPct = ref(50);
    const containerEl = ref(null);
    const imgSize = ref({width: 0, height: 0});  // updated on image load event

    function hide() { state.diff.visible = false; }

    // Reset slider when the modal opens
    watch(() => state.diff.visible, (v) => {
      if (v) sliderPct.value = 50;
    });

    // Drag logic
    let dragging = false;

    function startDrag(e) {
      e.preventDefault();
      dragging = true;
      const mm = (ev) => {
        if (!containerEl.value) return;
        const rect = containerEl.value.getBoundingClientRect();
        sliderPct.value = Math.max(0, Math.min(100, ((ev.clientX - rect.left) / rect.width) * 100));
      };
      const mu = () => {
        dragging = false;
        window.removeEventListener('mousemove', mm);
        window.removeEventListener('mouseup', mu);
      };
      window.addEventListener('mousemove', mm);
      window.addEventListener('mouseup', mu);
    }

    function replaceRef() {
      send('replace_reference', {
        ref_name: state.diff.refName,
        actual_path: state.diff.actualPath,
      });
      hide();
    }

    function onImgLoad(event) {
      imgSize.value.width = event.target.naturalWidth;
      imgSize.value.height = event.target.naturalHeight;
    }

    const overlayStyle = () => ({
      clipPath: `inset(0 ${100 - sliderPct.value}% 0 0)`,
    });

    const sliderStyle = () => ({
      left: `${sliderPct.value}%`,
    });

    return {
      state,
      hide,
      startDrag,
      replaceRef,
      onImgLoad,
      overlayStyle,
      sliderStyle,
      containerEl,
      imgSize,
    };
  },

  template: `
    <div id="diff-modal" class="overlay-screen" v-show="state.diff.visible">
      <div class="diff-modal-card">
        <div class="diff-modal-header">
          <span>Screenshot mismatch</span>
          <button class="btn-icon" @click="hide"><Icon name="x" /></button>
        </div>
        <div class="diff-modal-tags">
          <span class="screenshot-tag screenshot-tag-actual">ACTUAL RESULT</span>
          <span class="screenshot-tag screenshot-tag-reference">REFERENCE</span>
        </div>
        <div id="diff-container" class="diff-container" ref="containerEl">
          <img class="diff-img" :src="state.diff.refPath ? '/api/img?path=' + encodeURIComponent(state.diff.refPath) : ''" />
          <img
            class="diff-img diff-img-overlay"
            :src="state.diff.actualPath ? '/api/img?path=' + encodeURIComponent(state.diff.actualPath) : ''"
            :style="overlayStyle()"
            @load="onImgLoad"
          />
          <RegionOverlay 
            :regions="state.diff.regions"
            :ignore-regions="state.diff.ignoreRegions"
            :image-dimensions="imgSize" />
          <div class="diff-slider" :style="sliderStyle()" @mousedown="startDrag"></div>
        </div>
        <div class="diff-actions">
          <button class="btn-danger" @click="replaceRef">
            <Icon name="refresh-cw" /> Replace reference
          </button>
          <button class="btn-ghost" @click="hide">Close</button>
        </div>
      </div>
    </div>`,
});

/** Imperatively open the diff modal (called from step popover / step list). */
export function showDiffModal({refPath, actualPath, refName, regions, ignoreRegions}) {
  // state is already imported above
  state.diff.refPath       = refPath;
  state.diff.actualPath    = actualPath;
  state.diff.refName       = refName;
  state.diff.visible       = true;
  state.diff.regions       = regions ?? null;
  state.diff.ignoreRegions = ignoreRegions ?? null;
}
