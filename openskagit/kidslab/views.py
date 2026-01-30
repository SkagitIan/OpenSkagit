from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect, render

from .forms import CardUploadForm
from .utils import get_active_cards_payload


def index(request):
    cards = get_active_cards_payload()
    return render(request, "kidslab/index.html", {"cards": cards})


@staff_member_required
def add_card(request):
    if request.method == "POST":
        form = CardUploadForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "New card added to the Kids Lab deck.")
            return redirect("kidslab:add")
    else:
        form = CardUploadForm()

    return render(request, "kidslab/add_card.html", {"form": form})
