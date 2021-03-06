from django.core.exceptions import ValidationError
from django.forms.util import ErrorList, ErrorDict
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render

from cyder.cydns.soa.forms import SOAForm
from cyder.cydns.soa.models import SOA, SOAKeyValue
from cyder.base.utils import tablefy
from cyder.cydns.views import CydnsCreateView
from cyder.cydns.views import CydnsDeleteView
from cyder.cydns.views import CydnsDetailView
from cyder.cydns.views import CydnsListView
from cyder.cydns.views import CydnsUpdateView

from cyder.cydhcp.keyvalue.utils import get_aa, get_docstrings, get_attrs
from cyder.cydhcp.keyvalue.utils import update_attrs, dict_to_kv
import json as json


class SOAView(object):
    model = SOA
    form_class = SOAForm
    queryset = SOA.objects.all()
    extra_context = {'obj_type': 'soa'}


class SOADetailView(SOAView, CydnsDetailView):
    template_name = 'soa/soa_detail.html'

    def get_context_data(self, **kwargs):
        context = super(SOADetailView, self).get_context_data(**kwargs)
        soa = kwargs.get('object', False)
        if not soa:
            return soa

        context = dict({
            'domain_table': tablefy(soa.domain_set.filter(is_reverse=False)
                                    .order_by('master_domain')
                                    .select_related()),
            'rdomain_table': tablefy(soa.domain_set.filter(is_reverse=True)
                                     .order_by('master_domain')
                                     .select_related())
        }.items() + context.items())

        return context


def delete_soa_attr(request, attr_pk):
    """
    An view destined to be called by ajax to remove an attr.
    """
    attr = get_object_or_404(SOAKeyValue, pk=attr_pk)
    attr.delete()
    return HttpResponse("Attribute Removed.")


def update_soa(request, soa_pk):
    soa = get_object_or_404(SOA, pk=soa_pk)
    attrs = soa.soakeyvalue_set.all()
    docs = get_docstrings(SOAKeyValue())
    aa = get_aa(SOAKeyValue())
    if request.method == 'POST':
        form = SOAForm(request.POST, instance=soa)
        try:
            if not form.is_valid():
                return render(request, 'soa/soa_edit.html', {
                    'soa': soa,
                    'form': form,
                    'attrs': attrs,
                    'docs': docs,
                    'aa': json.dumps(aa)
                })
            else:
                # Handle key value stuff.
                kv = None
                kv = get_attrs(request.POST)
                update_attrs(kv, attrs, SOAKeyValue, soa, 'soa')
                soa = form.save()
                return redirect(soa.get_update_url())
        except ValidationError, e:
            if form._errors is None:
                form._errors = ErrorDict()
            form._errors['__all__'] = ErrorList(e.messages)
            if kv:
                attrs = dict_to_kv(kv, SOAKeyValue)
            return render(request, 'soa/soa_edit.html', {
                'soa': soa,
                'form': form,
                'attrs': attrs,
                'docs': docs,
                'aa': json.dumps(aa)
            })

    else:
        form = SOAForm(instance=soa)
        return render(request, 'soa/soa_edit.html', {
            'soa': soa,
            'form': form,
            'attrs': attrs,
            'docs': docs,
            'aa': json.dumps(aa)
        })
