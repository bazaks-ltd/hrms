<script setup>
import { ref, watch, defineProps, onMounted } from "vue";

const props = defineProps(["modelValue", "doctype", "title", "field"]);
const emit = defineEmits(["update:modelValue"]);
const model = ref(props.modelValue);

const lists = ref([]);
const filteredList = ref(lists.value);
const isListHidden = ref(true);
const inputText = ref("");

const selectedIndex = ref(-1);

onMounted(() => {
  frappe.db
    .get_list(props.doctype, {
      fields: [props.field || "name"],
      limit: 0,
    })
    .then((res) => {
      lists.value = res.map((r) => (props.field ? r[props.field] : r.name));
      filteredList.value = lists.value;
    });
});

watch(inputText, () => {
  selectedIndex.value = -1;
  const o = [...lists.value];
  filteredList.value = o.filter((f) => {
    return f.toLowerCase().includes(inputText.value.toLowerCase());
  });
});

const onLinkClicked = (l) => {
  model.value = l;
  isListHidden.value = true;

  emit("update:modelValue", l);
};

const onKeyUpDown = (diff) => {
  const length = filteredList.value.length;
  if (diff > 0) {
    const index = selectedIndex.value + 1;
    if (index <= length - 1) {
      selectedIndex.value = index;
    } else {
      selectedIndex.value = 0;
    }
  } else {
    const index = selectedIndex.value - 1;
    if (index >= 0) {
      selectedIndex.value = index;
    } else {
      selectedIndex.value = length - 1;
    }
  }
};
</script>
<template>
  <div class="form-column col-sm-4">
    <form v-on:submit.prevent>
      <div
        class="frappe-control"
        data-fieldtype="Link"
        data-fieldname="department"
      >
        <div class="form-group">
          <div class="clearfix">
            <label class="control-label">{{ props.title }}</label>
          </div>
          <button
            v-if="model"
            class="btn btn-primary"
            type="button"
            @click="
              model = null;
              $emit('update:modelValue', undefined);
            "
          >
            {{ model }} <i class="fa fa-close"></i>
          </button>
          <div v-else class="control-input-wrapper">
            <div class="control-input">
              <div class="link-field ui-front" style="position: relative">
                <div class="awesomplete">
                  <input
                    type="text"
                    class="form-control"
                    autocomplete="off"
                    spellcheck="false"
                    @focus="isListHidden = false"
                    v-model="inputText"
                    @blur="isListHidden = true"
                    @keydown.down="onKeyUpDown(1)"
                    @keydown.up="onKeyUpDown(-1)"
                    @keydown.enter="onLinkClicked(filteredList[selectedIndex])"
                    @keydown.tab=""
                  />
                  <ul role="listbox" :hidden="isListHidden">
                    <li
                      v-for="(l, i) in filteredList"
                      @mousedown.prevent="onLinkClicked(l)"
                      :aria-selected="i === selectedIndex"
                    >
                      <a>
                        <p>
                          <strong>{{ l }}</strong>
                        </p>
                      </a>
                    </li>
                  </ul>
                </div>
              </div>
            </div>
            <div
              class="control-value like-disabled-input"
              style="display: none"
            ></div>
            <p class="help-box small text-muted"></p>
          </div>
        </div>
      </div>
    </form>
  </div>
</template>
