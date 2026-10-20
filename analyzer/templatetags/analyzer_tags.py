from django import template

register = template.Library()

RANK_CLASSES = {
    "A": "bg-emerald-100 text-emerald-800",
    "B": "bg-green-100 text-green-800",
    "C": "bg-yellow-100 text-yellow-800",
    "D": "bg-orange-100 text-orange-800",
    "E": "bg-orange-200 text-orange-900",
    "F": "bg-red-100 text-red-800",
}


@register.filter
def rank_classes(rank):
    return RANK_CLASSES.get(rank, "bg-gray-100 text-gray-600")


@register.filter
def mi_classes(mi):
    if mi is None:
        return "text-gray-400"
    if mi >= 65:
        return "text-emerald-700"
    if mi >= 20:
        return "text-amber-600"
    return "text-red-600 font-semibold"


@register.filter
def basename(path):
    return path.rsplit("/", 1)[-1]


@register.filter
def dirname(path):
    return path.rsplit("/", 1)[0] if "/" in path else ""


@register.filter
def percent_of(value, maximum):
    """Width percentage (0-100) of value relative to maximum, for inline bar charts."""
    try:
        return max(0, min(100, round(float(value) / float(maximum) * 100, 1)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.simple_tag(takes_context=True)
def sort_query(context, column):
    """Query string to sort the files table by `column`, toggling direction if already sorted."""
    current, direction = context.get("sort"), context.get("dir")
    new_dir = "asc" if current == column and direction == "desc" else "desc"
    params = context["request"].GET.copy()
    params["sort"], params["dir"] = column, new_dir
    params.pop("page", None)
    return params.urlencode()


WIZARD_STEPS = ["Repository", "Options", "Analyse", "Results"]


@register.inclusion_tag("analyzer/partials/wizard_steps.html")
def wizard_steps(current):
    return {"steps": list(enumerate(WIZARD_STEPS, 1)), "current": current}
