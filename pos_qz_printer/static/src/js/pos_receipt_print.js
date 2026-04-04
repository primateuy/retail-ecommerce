/** @odoo-module **/
/**
 * @typedef {import("@web/core/orm_service").ORM} ORM
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { ConfirmPopup } from "@point_of_sale/app/utils/confirm_popup/confirm_popup";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { PrinterService } from "@point_of_sale/app/printer/printer_service";
import { useService } from "@web/core/utils/hooks";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

import { patch } from "@web/core/utils/patch";

var qzVersion = 0;
var data_to_print = ''
var company_id = null;
var printer_name = null;

    function findVersion() {
        qz.api.getVersion().then(function(data) {
            qzVersion = data;
        });
    }

    function startConnection(config) {
        qz.security.setCertificatePromise(function(resolve, reject) {
            $.ajax("/pos_qz_printer/static/src/lib/digital-certificate.txt").then(resolve, reject);
        });

        function strip(key) {
            if (key.indexOf('-----') !== -1) {
                return key.split('-----')[2].replace(/\r?\n|\r/g, '');
            }
        }

        if (!qz.websocket.isActive()) {
            console.log('Waiting default');
            qz.websocket.connect(config).then(function() {
                console.log('Active success');
                findVersion();
                findPrinters();
            });
        } else {
            console.log('An active connection with QZ already exists.', 'alert-warning');
        }
    }

    function findPrinters() {
        setPrinter(printer_name);
    }

    function setPrinter(printer) {
        var cf = getUpdatedConfig();
        cf.setPrinter(printer);
        if (typeof printer === 'object' && printer.name == undefined) {
            var shown;
            if (printer.file != undefined) {
                shown = "<em>FILE:</em> " + printer.file;
            }
            if (printer.host != undefined) {
                shown = "<em>HOST:</em> " + printer.host + ":" + printer.port;
            }
        } else {
            if (printer.name != undefined) {
                printer = printer.name;
            }

            if (printer == undefined) {
                printer = 'NONE';
            }
            printReceipt();
        }
    }
    /// QZ Config ///
    var cfg = null;

    function getUpdatedConfig() {
        if (cfg == null) {
            cfg = qz.configs.create(null);
        }

        cfg.reconfigure({
            copies: 1,
            margins: {top: 0, left: 0.75},

        });
        return cfg
    }
    function printReceipt() {
        var config = getUpdatedConfig();
            var printData =
            [
                data_to_print
           ];
            qz.print(config, printData).catch(function(e) { console.error(e); });
        location.reload();
    }

patch(ReceiptScreen.prototype, {
    async printReceipt() {
        const el = await this.printer.renderer.toHtml(OrderReceipt, {
                data: this.pos.get_order().export_for_printing(),
                formatCurrency: this.env.utils.formatCurrency,
            })
        data_to_print = el.outerText
        company_id = this.pos.company.id;
        const response = await this.orm.read('res.company', [company_id], ['pos_printer']);
        if (response){
            printer_name = response[0].pos_printer
            startConnection()
        }
        else{
            this.buttonPrintReceipt.el.className = "fa fa-fw fa-spin fa-circle-o-notch";
            const isPrinted = await this.printer.print(
                OrderReceipt,
                {
                    data: this.pos.get_order().export_for_printing(),
                    formatCurrency: this.env.utils.formatCurrency,
                },
                { webPrintFallback: true }
            );

            if (isPrinted) {
                this.currentOrder._printed = true;
            }

            if (this.buttonPrintReceipt.el) {
                this.buttonPrintReceipt.el.className = "fa fa-print";
            }
        }
    }
});