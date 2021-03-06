from django.db import models

from cyder.cydhcp.keyvalue.base_option import CommonOption
from cyder.cydhcp.range.models import Range
from cyder.cydhcp.utils import format_mac
from cyder.cydhcp.vrf.models import Vrf
from cyder.cydhcp.workgroup.models import Workgroup
from cyder.core.ctnr.models import Ctnr
from cyder.core.system.models import System
from cyder.cydns.domain.models import Domain
from cyder.base.mixins import ObjectUrlMixin


class DynamicInterface(models.Model, ObjectUrlMixin):
    ctnr = models.ForeignKey(Ctnr, null=False)
    range = models.ForeignKey(Range, null=False)
    workgroup = models.ForeignKey(Workgroup, null=True)
    mac = models.CharField(max_length=19,
                           help_text="Mac address in format XX:XX:XX:XX:XX:XX")
    system = models.ForeignKey(System,
                               null=True,
                               blank=True,
                               help_text="System to associate "
                                         "the interface with")
    vrf = models.ForeignKey(Vrf, null=True)
    domain = models.ForeignKey(Domain, null=True)
    dhcp_enabled = models.BooleanField(default=True)
    dns_enabled = models.BooleanField(default=True)
    search_fields = ('mac')

    class Meta:
        db_table = 'dynamic_interface'

    def details(self):
        data = super(DynamicInterface, self).details()
        data['data'] = [
            ('System', 'system', self.system),
            ('Mac', 'mac', self.mac),
            ('Range', 'range', self.range),
            ('Workgroup', 'workgroup', self.workgroup),
            ('Vrf', 'vrf', self.vrf),
            ('Domain', 'domain', self.domain)]
        return data

    def build_host(self):
        build_str = "\thost {0} {{\n".format(self.get_fqdn())
        build_str += "\t\thardware ethernet {0};\n".format(
            format_mac(self.mac))
        """
        options = self.dynamicintrkeyvalue_set.filter(is_option=True)
        statements = self.dynamicintrkeyvalue_set.filter(is_statement=True)
        if options:
            build_str += "\t\t# Host Options\n"
            build_str += join_dhcp_args(options, depth=2)
        if statements:
            build_str += "\t\t# Host Statemets\n"
            build_str += join_dhcp_args(statements, depth=2)
        """
        build_str += "\t}\n\n"
        return build_str

    def build_subclass(self, allowed):
        return "subclass \"{0}:{1}:{2}\" 1:{3};\n".format(
            allowed, self.range.start_str, self.range.end_str,
            format_mac(self.mac))

    def get_fqdn(self):
        if not self.system.name:
            return self.domain.name
        else:
            return "{0}.{1}".format(self.system.name, self.domain.name)


class DynamicIntrKeyValue(CommonOption):
    intr = models.ForeignKey(DynamicInterface, null=False)

    class Meta:
        db_table = "dynamic_interface_kv"
        unique_together = "key", "value", "intr"
