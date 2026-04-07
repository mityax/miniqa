/**
 * Icon.js — Renders a feather icon inline as an SVG.
 *
 * Usage: <Icon name="play" />
 *        <Icon name="loader" :xl="true" />
 *        <Icon name="loader" :spin="true" />
 *
 * Replaces all `<svg data-feather="...">` + feather.replace() patterns
 * from the original vanilla codebase.
 */

import {computed, defineComponent} from 'vue';

export const Icon = defineComponent({
  name: 'Icon',

  props: {
    name:       { type: String,  required: true  },
    xl:         { type: Boolean, default: false   },
    spin:       { type: Boolean, default: false   },
    extraClass: { type: String,  default: ''      },
  },

  setup(props) {
    const svgHtml = computed(() => {
      const icon = window.feather?.icons?.[props.name];
      if (!icon) return '';

      const classes = [
        props.xl   ? 'icon icon-xl' : 'icon',
        props.spin ? 'icon-spin'    : '',
        props.extraClass            || '',
      ].filter(Boolean).join(' ');

      return icon.toSvg({ 'stroke-width': 1.75, class: classes });
    });

    return { svgHtml };
  },

  template: `<span style="display:contents" v-html="svgHtml"></span>`,
});
