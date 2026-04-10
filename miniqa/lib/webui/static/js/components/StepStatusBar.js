import {computed, defineComponent, onMounted, onUnmounted, ref,} from 'vue';
import {editorRef, state} from '../state.js';
import {findStepLines} from '../utils.js';
import {showDiffModal} from './modals/DiffModal.js';
import {Icon} from './Icon.js';

// -- StepPopover ---------------------------------------------------------------

const StepPopover = defineComponent({
  name: 'StepPopover',
  components: { Icon },

  props: {
    stepIdx: { type: Number,  required: true },
    sr:      { type: Object,  required: true },
    top:     { type: Number,  default: 0     },
    left:    { type: Number,  default: 34    },
  },

  emits: ['close'],

  setup(props, { emit }) {
    const isFailed    = computed(() => props.sr?.success === false);
    const headerColor = computed(() => isFailed.value ? 'var(--c-error)' : 'var(--c-success)');
    const headerLabel = computed(() => isFailed.value ? 'Failed' : 'Passed');

    const refShot = computed(() =>
      (props.sr?.screenshots ?? []).find(s => s.tag === 'reference')
    );
    const actShot = computed(() =>
      (props.sr?.screenshots ?? []).find(s => s.tag === 'actual') ??
      (props.sr?.screenshots ?? []).find(s => s.tag === 'after')
    );
    const hasDiff = computed(() => !!(refShot.value && actShot.value));

    function openDiff() {
      showDiffModal({
        refPath: refShot.value.path,
        actualPath: actShot.value.path,
        refName: refShot.value.name ?? 'Reference',
        regions: props.sr.exception_regions,
        ignoreRegions: props.sr.exception_ignore_regions,
      });
    }

    function openLightbox(path) {
      state.lightbox.src     = `/api/img?path=${encodeURIComponent(path)}`;
      state.lightbox.visible = true;
    }

    function imgUrl(p) { return `/api/img?path=${encodeURIComponent(p)}`; }

    return {
      isFailed, headerColor, headerLabel,
      refShot, actShot, hasDiff,
      openDiff, openLightbox, imgUrl,
    };
  },

  template: `
    <div
      id="step-popover"
      :data-step="stepIdx"
      :style="{ top: top + 'px', left: left + 'px' }"
    >
      <div class="step-popover-header">
        <span>
          Step {{ stepIdx + 1 }} —
          <span :style="{ color: headerColor }">{{ headerLabel }}</span>
        </span>
        <button class="btn-icon btn-sm" @click="$emit('close')">
          <Icon name="x" />
        </button>
      </div>

      <div class="step-popover-body">
        <div
          v-if="sr.exception_type"
          class="step-popover-message"
        ><strong>{{ sr.exception_type }}</strong>{{ sr.exception_msg ? ': ' + sr.exception_msg : '' }}</div>
        <div
          v-else-if="sr.message"
          class="step-popover-message"
        >{{ sr.message }}</div>

        <button
          v-if="hasDiff"
          class="btn-ghost btn-sm center"
          @click="openDiff"
        >
          <Icon name="layers" /> Diff
        </button>

        <div class="step-screenshots" v-if="sr.screenshots?.length">
          <div
            v-for="(sc, si) in sr.screenshots"
            :key="si"
            class="step-screenshot-wrap"
            :data-path="sc.path"
            style="cursor:pointer"
            title="Click to enlarge"
            @click="openLightbox(sc.path)"
          >
            <span
              v-if="sc.tag"
              :class="['screenshot-tag', 'screenshot-tag-' + sc.tag]"
            >{{ sc.tag }}</span>
            <img
              class="step-screenshot-thumb"
              :src="imgUrl(sc.path)"
              :alt="'Screenshot ' + si"
              loading="lazy"
            />
          </div>
        </div>
      </div>
    </div>`,
});

// -- StepStatusBar -------------------------------------------------------------

export const StepStatusBar = defineComponent({
  name: 'StepStatusBar',
  components: { Icon, StepPopover },

  setup() {
    const barEl    = ref(null);
    const icons    = ref([]);

    const popover  = computed(() => state.stepPopover);

    // Recompute icon positions whenever the editor scrolls or step_results change
    function refresh() {
      const editor = editorRef.get();
      if (!editor || !barEl.value) { icons.value = []; return; }

      const yaml        = editor.getValue();
      const stepLines   = findStepLines(yaml);
      if (!stepLines.length) { icons.value = []; return; }

      const renderer   = editor.renderer;
      const lineHeight = renderer.lineHeight || 16;
      const scrollTop  = editor.session.getScrollTop();
      const barHeight  = barEl.value.clientHeight;

      const { current_step, step_results } = state.edit;

      icons.value = stepLines.map((lineNum, stepIdx) => {
        const pixelY = lineNum * lineHeight - scrollTop + lineHeight / 2;
        if (pixelY < 0 || pixelY > barHeight + lineHeight) return null;

        const sr        = step_results?.[stepIdx] ?? null;
        const isCur     = current_step === stepIdx;
        const isFailed  = sr?.success === false;
        const isOk      = sr?.success === true || (current_step !== null && stepIdx < current_step);
        const hasResults= !!(sr?.message || sr?.exception_type || sr?.screenshots?.length);

        let statusClass = 'step-status-pending';
        let iconName    = 'minus';
        if      (isCur)    { statusClass = 'step-status-running'; iconName = 'loader';       }
        else if (isFailed) { statusClass = 'step-status-failed';  iconName = 'alert-circle'; }
        else if (isOk)     { statusClass = 'step-status-success'; iconName = 'check-circle'; }

        return {
          stepIdx, pixelY, statusClass, iconName, hasResults, sr,
          spin: statusClass === 'step-status-running',
        };
      }).filter(Boolean);

      const popoverIcon = icons.value.find(ic => ic.stepIdx === state.stepPopover.stepIdx);
      if (popoverIcon) {
        state.stepPopover.top = Math.max(4, popoverIcon.pixelY - 16);
      }
    }

    // Watch for changes that require a re-render
    let _unsubEditor = null;

    function attachEditorListeners() {
      const editor = editorRef.get();
      if (!editor) return;
      editor.session.on('change',          refresh);
      editor.session.on('changeScrollTop', refresh);
    }

    // Interval poll because the editor reference can change (new file opened)
    let _pollInterval = null;
    onMounted(() => {
      refresh();
      _pollInterval = setInterval(() => {
        const editor = editorRef.get();
        if (editor && !editor._statusBarAttached) {
          editor._statusBarAttached = true;
          editor.session.on('change',          refresh);
          editor.session.on('changeScrollTop', refresh);
        }
        refresh();
      }, 100);
    });
    onUnmounted(() => clearInterval(_pollInterval));

    // -- Popover ----------------------------------------------------------

    function togglePopover(icon) {
      if (!icon.hasResults) return;
      const pop = state.stepPopover;
      if (pop.visible && pop.stepIdx === icon.stepIdx) {
        pop.visible = false;
        return;
      }
      pop.stepIdx = icon.stepIdx;
      pop.sr      = icon.sr;
      pop.top     = Math.max(4, icon.pixelY - 16);
      pop.left    = 34;
      pop.visible = true;
    }

    function closePopover() { state.stepPopover.visible = false; }

    // Close popover on outside click / Escape
    function onDocClick(e) {
      if (!state.stepPopover.visible) return;
      // Check if click was inside the popover or the status bar
      if (barEl.value?.contains(e.target)) return;
      // The popover is a child of barEl in the template, so the above covers it
      closePopover();
    }
    function onDocKey(e) {
      if (e.key === 'Escape') closePopover();
    }

    onMounted(() => {
      document.addEventListener('click',   onDocClick);
      document.addEventListener('keydown', onDocKey);
    });
    onUnmounted(() => {
      document.removeEventListener('click',   onDocClick);
      document.removeEventListener('keydown', onDocKey);
    });

    // Expose openPopover so the edit view can call it for auto-open
    function openPopover(stepIdx) {
      const icon = icons.value.find(ic => ic.stepIdx === stepIdx);
      if (icon) togglePopover(icon);
    }

    return { barEl, icons, popover, togglePopover, closePopover, openPopover };
  },

  template: `
    <div id="step-status-bar" ref="barEl">
      <div
        v-for="icon in icons"
        :key="icon.stepIdx"
        :class="['step-status-icon', icon.statusClass, icon.hasResults ? 'clickable' : '']"
        :style="{ top: icon.pixelY + 'px' }"
        @click.stop="togglePopover(icon)"
      >
        <Icon :name="icon.iconName" :spin="icon.spin" />
      </div>

      <StepPopover
        v-if="popover.visible && popover.sr"
        :step-idx="popover.stepIdx"
        :sr="popover.sr"
        :top="popover.top"
        :left="popover.left"
        @close="closePopover"
      />
    </div>`,
});
