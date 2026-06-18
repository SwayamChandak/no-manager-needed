import { Checkbox } from "./ui/checkbox";

function ActionCheckboxGroup({ items, selected, onChange }) {
  const toggle = (label) => {
    if (selected.includes(label)) {
      onChange(selected.filter((l) => l !== label));
    } else {
      onChange([...selected, label]);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">
        Proposed Actions — uncheck to exclude from execution
      </p>
      {items.map((item) => (
        <div key={item.label} className="flex items-start gap-2">
          <Checkbox
            id={item.label}
            checked={selected.includes(item.label)}
            onCheckedChange={() => toggle(item.label)}
          />
          <label
            htmlFor={item.label}
            className="text-sm leading-relaxed cursor-pointer"
          >
            {item.label}
          </label>
        </div>
      ))}
    </div>
  );
}

export default ActionCheckboxGroup;
