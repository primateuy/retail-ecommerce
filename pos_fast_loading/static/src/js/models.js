/** @odoo-module */
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { PosDB } from "@point_of_sale/app/store/db";
import { Loader } from "@point_of_sale/app/loader/loader";
import { unaccent } from "@web/core/utils/strings";
import { roundPrecision as round_pr, floatIsZero } from "@web/core/utils/numbers";
import { PosCollection, Order, Product } from "@point_of_sale/app/store/models";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this.loader = Loader;
    },

    /*
     ==============================FLow====================================

                              load_server_data
                                     ||
                                     ||=> _processData
                                     ||
                                     ||=> _loadMongoServerConfig
                                     ||
                              (indexedDB in window)
                                     ||
                            True     ||     False
                      ======================================
                      ||                                  ||
                      ||                                  ||
                      * custom_product_load               * _loadProductProduct
                      * custom_partner_load               * addPartners
    */

    //@override to add the pos context
    async load_server_data() {
        var self = this;
        self.product_loaded_using_index = false;
        self.partner_loaded_using_index = false;
        var context = await self.update_required_context();
        const loadedData = await this.orm.call("pos.session", "load_pos_data", [odoo.pos_session_id], { context: context });
        await this._processData(loadedData);
        return this.after_load_server_data();
    },
    //@override
    async _processData(loadedData) {
        this.version = loadedData["version"];
        this.company = loadedData["res.company"];
        this.dp = loadedData["decimal.precision"];
        this.units = loadedData["uom.uom"];
        this.units_by_id = loadedData["units_by_id"];
        this.states = loadedData["res.country.state"];
        this.countries = loadedData["res.country"];
        this.langs = loadedData["res.lang"];
        this.taxes = loadedData["account.tax"];
        this.taxes_by_id = loadedData["taxes_by_id"];
        this.pos_session = loadedData["pos.session"];
        this._loadPosSession();
        this.config = loadedData["pos.config"];
        this._loadPoSConfig();
        this.bills = loadedData["pos.bill"];
        this.partners = loadedData["res.partner"];
        this.addPartners(this.partners);
        this.picking_type = loadedData["stock.picking.type"];
        this.user = loadedData["res.users"];
        this.pricelists = loadedData["product.pricelist"];
        this.default_pricelist = loadedData["default_pricelist"];
        this.currency = loadedData["res.currency"];
        this.db.add_attributes(loadedData["attributes_by_ptal_id"]);
        this.db.add_categories(loadedData["pos.category"]);
        this.db.add_combos(loadedData["pos.combo"]);
        this.db.add_combo_lines(loadedData["pos.combo.line"]);

        await this.db._loadMongoServerConfig(loadedData["mongo.server.config"]);
        if (!("indexedDB" in window)) {
            console.log("This browser doesn't support IndexedDB");
            this._loadProductProduct(loadedData["product.product"]);
            this.partners = loadedData["res.partner"];
            this.addPartners(this.partners);
        } else {
            this.custom_product_load(loadedData["product.product"]);
            this.custom_partner_load(loadedData["res.partner"]);
        }

        this.db.add_packagings(loadedData["product.packaging"]);
        this.attributes_by_ptal_id = loadedData["attributes_by_ptal_id"];
        this._add_ptal_ids_by_ptav_id(this.attributes_by_ptal_id);
        this.cash_rounding = loadedData["account.cash.rounding"];
        this.payment_methods = loadedData["pos.payment.method"];
        this._loadPosPaymentMethod();
        this.fiscal_positions = loadedData["account.fiscal.position"];
        this.base_url = loadedData["base_url"];
        this.pos_has_valid_product = loadedData["pos_has_valid_product"];
        this.db.addProductIdsToNotDisplay(loadedData["pos_special_products_ids"]);
        this.partner_commercial_fields = loadedData["partner_commercial_fields"];
        this.show_product_images = loadedData["show_product_images"] === "yes";
        this.show_category_images = loadedData["show_category_images"] === "yes";
        await this._loadPosPrinters(loadedData["pos.printer"]);
        this.open_orders_json = loadedData["open_orders"];
    },
    send_current_order_to_customer_facing_display() {
        var self = this;
        if (self.config) {
            super.send_current_order_to_customer_facing_display();
        }
    },
    update_required_context() {
        return new Promise((resolve, reject) => {
            var self = this;
            var context = {};
            var data = [];
            var request = window.indexedDB.open("cacheDate", 1);
            request.onsuccess = async function (event) {
                var db = event.target.result;
                if (db.objectStoreNames.contains("last_update")) {
                    var res = await getRecordsIndexedDB(db, "last_update");
                    context["sync_from_mongo"] = true;
                    context["is_indexed_updated"] = res;
                    // localStorage.setItem("cache_last_update", JSON.stringify(res));
                    resolve(context);
                }
            };
            request.onerror = function (event) {
                reject();
            };
            request.onupgradeneeded = function (event) {
                var db = event.target.result;
                var itemsStore = db.createObjectStore("last_update", {
                    keyPath: "id",
                });
            };
            // if (!context.length) {
            //     context["sync_from_mongo"] = true;
            //     data.push(JSON.parse(localStorage.getItem("cache_last_update")));
            //     context["is_indexed_updated"] = data;
            // }
        });
           
    },
    async loadRemCustomersFast() {
        let partners = [];
        let page = 1;
        var self = this;
        this.ui.block("Loading Remaining Customers...")
        do {
            partners = await this.orm.call("mongo.server.config", "load_rem_customer", [0, page, self.company.id]);

            if (partners) {
                self.addPartners(partners);
                self.updatePartnerIDB(partners);
            }
            page += 1;
        } while (partners.length);
        this.ui.unblock(); // The page is blocked at this point, unblock it.
    },
    async loadRemProductsFast() {
        let products = [];
        let page = 1;
        var self = this;
        do {
            products = await this.orm.call("mongo.server.config", "load_rem_product", [0, page, self.company.id, self.config.current_session_id[0]]);
            if (products.length) {
                self._loadProductProduct(products);
                self.updateProductsIDB(products);
            }
            page += 1;
        } while (products.length);
        this.ui.unblock(); // The page is blocked at this point, unblock it.
    },
    custom_product_load(products) {
        var self = this;
        self.db.product_loaded = false;
        if (products.length) {
            $.each(products, function (seq, obj) {
                obj.pos = self;
            });
            self._loadProductProduct(products);
            self.loadRemProductsFast();
            console.log("product loaded through default...........");
        }
        this.ui.block('Product Loading...')
        var request = window.indexedDB.open("Product", 1);
        request.onsuccess = async function (event) {
            var db = event.target.result;
            if (!products.length) {
                var res = await getRecordsIndexedDB(db, "products")
                    $.each(res, function (seq, obj) {
                        obj.pos = self;
                    });
                self._loadProductProduct(res);
                self.product_loaded_using_index = true;
                console.log("product loaded through indexdb...........");
                self.ui.unblock(); // The page is blocked at this point, unblock it.
                
            } else {
                if (db.objectStoreNames.contains("products")) {
                    try {
                        var product_transaction = db.transaction(
                            "products",
                            "readwrite"
                        );

                        var productsStore = product_transaction.objectStore("products");

                        /*************************************/
                        products.forEach(function (product) {
                            var data_store = productsStore.get(product.id);
                            data_store.onsuccess = function (event) {
                                var data = event.target.result;
                                data = product;
                                delete data["pos"];
                                delete data["env"];
                                delete data["applicablePricelistItems"];
                                productsStore.put(data);
                            };
                        });
                    } catch {
                        console.log("----exception---- products");
                    }
                }
            }
        };
        request.onupgradeneeded = function (event) {
            var db = event.target.result;
            var productsStore = db.createObjectStore("products", {
                keyPath: "id",
            });
        };
    },
    custom_partner_load(partners) {
        var self = this;
        if (partners.length) {
            self.partners = partners;
            self.addPartners(partners);
            console.log("partners loaded through default...........");
            self.loadRemCustomersFast();
        }
        var request = window.indexedDB.open("Partners", 1);
        request.onsuccess = function (event) {
            var db = event.target.result;
            if (!partners.length) {
                getRecordsIndexedDB(db, "partners").then(function (res) {
                    self.partners = res;
                    self.addPartners(res);
                });
                self.partner_loaded_using_index = true;
                console.log("partners loaded through indexdb...........");
            } else {
                if (db.objectStoreNames.contains("partners")) {
                    try {
                        var transaction = db.transaction("partners", "readwrite");
                        var partnersStore = transaction.objectStore("partners");
                        /*************************************/
                        partners.forEach(function (partner) {
                            var data_store = partnersStore.get(partner.id);
                            data_store.onsuccess = function (event) {
                                var data = event.target.result;
                                data = partner;
                                var requestUpdate = partnersStore.put(data);
                            };
                        });
                    } catch {
                        console.log("--- exception --- partners");
                    }
                }
            }
        };
        request.onupgradeneeded = function (event) {
            var db = event.target.result;
            var partnersStore = db.createObjectStore("partners", {
                keyPath: "id",
            });
        };

        // **********date*******
        var date_request = window.indexedDB.open("cacheDate", 1);
        date_request.onupgradeneeded = function (event) {
            var db = event.target.result;
            var lastUpdateTimeStore = db.createObjectStore("last_update", {
                keyPath: "id",
            });
        };
        date_request.onsuccess = function (event) {
            var date_db = event.target.result;
            try {
                var time_transaction = date_db.transaction(
                    "last_update",
                    "readwrite"
                );
                var lastTimeStore = time_transaction.objectStore("last_update");
                var last_date_store = lastTimeStore.get("time");
                last_date_store.onsuccess = function (event) {
                    var data = event.target.result;
                    data = {
                        id: "time",
                        time: self.db.mongo_config
                            ? self.db.mongo_config.cache_last_update_time
                            : undefined,
                    };
                    var last_updated_time = lastTimeStore.put(data);
                    // localStorage.setItem("cache_last_update", JSON.stringify(data));
                };
            } catch {
                console.log("-----exception---- last update");
            }
        };
    },
    updatePartnerIDB(partners, partner_deleted_record_ids) {
        var self = this;
        if (
            (partners && partners.length) ||
            (partner_deleted_record_ids && partner_deleted_record_ids.length)
        ) {
            if (!("indexedDB" in window)) {
                console.log("This browser doesn't support IndexedDB");
            } else {
                var request = window.indexedDB.open("Partners", 1);
                request.onsuccess = function (event) {
                    var db = event.target.result;
                    var transaction = db.transaction("partners", "readwrite");
                    var itemsStore = transaction.objectStore("partners");
                    if (partners && partners.length) {
                        partners.forEach(function (item) {
                            var data_store = itemsStore.get(item.id);
                            data_store.onsuccess = function (event) {
                                var data = event.target.result;
                                data = item;
                                const updateRequest = itemsStore.put(data);
                                updateRequest.onsuccess = (event) => {
                                    console.log(event)
                                  };

                                  updateRequest.onerror = (event) => {
                                    console.log(event)
                                  };
                                
                            };
                        });
                    }
                    if (
                        partner_deleted_record_ids &&
                        partner_deleted_record_ids.length
                    ) {
                        partner_deleted_record_ids.forEach(function (id) {
                            var data_store = itemsStore.get(id);
                            data_store.onsuccess = function (event) {
                                var data = event.target.result;
                                var requestUpdate = itemsStore.delete(id);
                            };
                        });
                    }
                };
            }
        }
    },
    updateProductsIDB(products, product_deleted_record_ids) {
        var self = this;
        if ((products && products.length) || (product_deleted_record_ids && product_deleted_record_ids.length)) {
            if (!("indexedDB" in window)) {
                console.log("This browser doesn't support IndexedDB");
            } else {
                var request = window.indexedDB.open("Product", 1);
                request.onsuccess = function (event) {
                    var db = event.target.result;
                    var transaction = db.transaction("products", "readwrite");
                    var itemsStore = transaction.objectStore("products");
                    if (products && products.length)
                        $.each(products, function (seq, item) {
                            var data_store = itemsStore.get(item.id);
                            data_store.onsuccess = function (event) {
                                var data = event.target.result;
                                data = item;
                                delete data["pos"];
                                delete data["env"];
                                delete data["applicablePricelistItems"];
                                var requestUpdate = itemsStore.put(data);
                            };
                        });
                    if (product_deleted_record_ids && product_deleted_record_ids.length)
                        $.each(product_deleted_record_ids, function (seq, id) {
                            var data_store = itemsStore.get(id);
                            data_store.onsuccess = function (event) {
                                var data = event.target.result;
                                var requestUpdate = itemsStore.delete(id);
                            };
                        });
                };
            }
        }
    },
    _loadProductProduct(products) {
        const productMap = {};
        const productTemplateMap = {};

        const modelProducts = products.map((product) => {
            product.taxes_id = product.taxes_id.filter(id => id in this.taxes_by_id);
            product.pos = this;
            product.env = this.env;
            product.applicablePricelistItems = {};
            productMap[product.id] = product;
            productTemplateMap[product.product_tmpl_id[0]] = (
                productTemplateMap[product.product_tmpl_id[0]] || []
            ).concat(product);
            return new Product(product);
        });

        for (const pricelist of this.pricelists) {
            for (const pricelistItem of pricelist.items) {
                if (pricelistItem.product_id) {
                    const product_id = pricelistItem.product_id[0];
                    const correspondingProduct = productMap[product_id];
                    if (correspondingProduct) {
                        this._assignApplicableItems(pricelist, correspondingProduct, pricelistItem);
                    }
                } else if (pricelistItem.product_tmpl_id) {
                    const product_tmpl_id = pricelistItem.product_tmpl_id[0];
                    const correspondingProducts = productTemplateMap[product_tmpl_id];
                    for (const correspondingProduct of correspondingProducts || []) {
                        this._assignApplicableItems(pricelist, correspondingProduct, pricelistItem);
                    }
                } else {
                    for (const correspondingProduct of products) {
                        this._assignApplicableItems(pricelist, correspondingProduct, pricelistItem);
                    }
                }
            }
        }
        this.db.add_products(modelProducts);
    }
});

patch(PosDB.prototype, {
    _loadMongoServerConfig(mongo_config) {
        var self = this;
        self.mongo_config = {};
        if (mongo_config && mongo_config.filter((a) => a.active_record)) {
            self.mongo_config = mongo_config.filter((a) => a.active_record)[0];
        }
    },
    get_product_by_category: function (category_id) {
        var product_ids = this.product_by_category_id[category_id];
        var list = [];
        if (product_ids) {
            for (
                var i = 0, len = Math.min(product_ids.length, this.limit);
                i < len;
                i++
            ) {
                const product = this.product_by_id[product_ids[i]];
                if (!(product.active && product.available_in_pos)) continue;
                if (!list.filter((a) => a.id === product.id).length)
                    list.push(product);
            }
        }
        return list;
    },
    search_product_in_category: function (category_id, query) {
        try {
            query = query.replace(
                /[\[\]\(\)\+\*\?\.\-\!\&\^\$\|\~\_\{\}\:\,\\\/]/g,
                "."
            );
            query = query.replace(/ /g, ".+");
            var re = RegExp("([0-9]+):.*?" + unaccent(query), "gi");
        } catch (_e) {
            return [];
        }
        var results = [];
        for (var i = 0; i < this.limit; i++) {
            var r = re.exec(this.category_search_string[category_id]);
            if (r) {
                var id = Number(r[1]);
                const product = this.get_product_by_id(id);
                if (!(product.active && product.available_in_pos)) continue;
                if (!results.filter((a) => a.id === product.id).length)
                    results.push(product);
            } else {
                break;
            }
        }
        return results;
    },
});

// ********************Function for getting data from indexedDB***************************************

function getRecordsIndexedDB(db, store) {
    return new Promise((resolve, reject) => {
        if (db.objectStoreNames.contains(store)) {
            try {
                var transaction = db.transaction(store, "readwrite");
                var objectStore = transaction.objectStore(store);
                var data_request = objectStore.getAll();
                data_request.onsuccess = function (event) {
                    resolve(event.target.result);
                };
                data_request.onerror = function (event) {
                    reject();
                };
            } catch (e) {
                console.log("No Items found", e);
            }
        }
    });
}
