import {computed, defineComponent} from 'vue';

export const RegionOverlay = defineComponent({
  name: 'RegionOverlay',
  props: {
      regions: { type: Array, required: true },
      ignoreRegions: { type: Array, required: true },
      imageDimensions: { type: Object, required: true },  // {width, height} - the natural image size in pixels
  },

  setup(props) {
    const coordinateToPct = (coord, maxExtent) =>
          coord.is_relative
              ? coord.value * 100
              : coord.value / maxExtent * 100;

    const diffRegionStyle = region => {
      return ({
        left:   coordinateToPct(region.x,      props.imageDimensions.width)  + '%',
        top:    coordinateToPct(region.y,      props.imageDimensions.height) + '%',
        width:  coordinateToPct(region.width,  props.imageDimensions.width)  + '%',
        height: coordinateToPct(region.height, props.imageDimensions.height) + '%',
      });
    };

    return {
      regions: computed(() => props.regions),
      ignoreRegions: computed(() => props.ignoreRegions),
      diffRegionStyle,
    };
  },

  template: `
    <div class="diff-regions-overlay">
        <div class="diff-region" v-for="region in regions" v-if="regions"
             :style="diffRegionStyle(region)"></div>
        <div class="diff-region diff-ignore-region" v-for="region in ignoreRegions" 
             v-if="ignoreRegions"
             :style="diffRegionStyle(region)"></div>
    </div>`,
});
