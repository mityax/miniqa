import {computed, defineComponent} from 'vue';
import {describeStep, escHtml} from '../utils.js';
import {showDiffModal} from './modals/DiffModal.js';
import {state} from '../state.js';
import {Icon} from './Icon.js';

/**
 * StepList — the collapsed step rows shown inside an expanded test item
 * on the pipeline view.  Stateless: all data comes via props.
 */
export const StepList = defineComponent({
  name: 'StepList',
  components: { Icon },

  props: {
    tc:         { type: Object,  default: null  },  // parsed YAML test object
    result:     { type: Object,  default: null  },  // test result from backend
    curStep:    { type: Number,  default: null  },  // currently running step index
    isCanceled: { type: Boolean, default: false },
  },

  setup(props) {
    const steps = computed(() => {
      const tc = props.tc;
      if (!tc?.steps?.length) return [];

      return tc.steps.map((step, i) => {
        const sr       = props.result?.step_results?.[i] ?? null;
        const isCur    = props.curStep === i;
        const isFailed = sr?.success === false || props.result?.failed_step === i;
        const isOk     = sr?.success === true  || i < props.curStep;

        let statusClass = 'pending';
        let iconName    = 'minus';
        if (isCur) {
          statusClass = props.isCanceled ? 'canceled' : 'running';
          iconName    = props.isCanceled ? 'x'        : 'loader';
        } else if (isFailed) { statusClass = 'failed';  iconName = 'alert-circle'; }
        else if (isOk)       { statusClass = 'success'; iconName = 'check';        }

        const screenshots = sr?.screenshots ?? [];
        const refShot     = screenshots.find(s => s.tag === 'reference');
        const actShot     = screenshots.find(s => s.tag === 'actual') ?? screenshots.find(s => s.tag === 'after');
        const hasDiff     = !!(refShot && actShot);

        return {
          i,
          step,
          sr,
          isCur,
          statusClass,
          iconName,
          screenshots,
          hasDiff,
          refShot,
          actShot,
          label:  describeStep(step),
          spin:   statusClass === 'running',
        };
      });
    });

    function openLightbox(path) {
      state.lightbox.src     = `/api/img?path=${encodeURIComponent(path)}`;
      state.lightbox.visible = true;
    }

    function openDiff(refShot, actShot, stepResult) {
      showDiffModal({
        refPath: refShot.path,
        actualPath: actShot.path,
        refName: refShot.name ?? 'Reference',
        regions: stepResult.exception_regions,
        ignoreRegions: stepResult.exception_ignore_regions,
      });
    }

    function imgUrl(path) {
      return `/api/img?path=${encodeURIComponent(path)}`;
    }

    return { steps, openLightbox, openDiff, imgUrl, escHtml };
  },

  template: `
    <div class="step-list" v-if="steps.length">
      <div
        v-for="s in steps"
        :key="s.i"
        :class="['step-row', 'step-' + s.statusClass, s.isCur ? 'step-current' : '']"
      >
        <span class="step-num">{{ s.i + 1 }}</span>
        <span :class="['step-icon', s.statusClass]">
          <Icon :name="s.iconName" :spin="s.spin" />
        </span>
        <span class="step-content">
          <strong v-html="s.label"></strong>
          <template v-if="s.sr?.message">
            <br><span style="color:var(--fg-muted)">{{ s.sr.message }}</span>
          </template>
          <div class="step-screenshots" v-if="s.screenshots.length">
            <div
              v-for="(sc, si) in s.screenshots"
              :key="si"
              class="step-screenshot-wrap"
              :data-path="sc.path"
              title="Click to enlarge"
              style="cursor:pointer"
              @click="openLightbox(sc.path)">
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
        </span>
        <span class="step-actions">
          <button
            v-if="s.hasDiff"
            class="btn-ghost btn-sm"
            @click="openDiff(s.refShot, s.actShot, s.sr)">
            <Icon name="layers" /> Diff
          </button>
        </span>
      </div>
    </div>`,
});
