context("FileUploader", () => {
	before(() => {
		cy.login();
		cy.visit("/app");
	});

	function open_upload_dialog() {
		cy.window()
			.its("frappe")
			.then((frappe) => {
				new frappe.ui.FileUploader();
			});
	}

	it("upload dialog api works", () => {
		open_upload_dialog();
		cy.get_open_dialog().should("contain", "Drag and drop files");
		cy.hide_dialog();
	});

	it("should accept dropped files", () => {
		open_upload_dialog();

		cy.get_open_dialog()
			.find(".file-upload-area")
			.selectFile("cypress/fixtures/example.json", {
				action: "drag-drop",
			});

		cy.get_open_dialog().find(".file-name").should("contain", "example.json");
		cy.intercept("POST", "/api/method/upload_file").as("upload_file");
		cy.get_open_dialog().findByRole("button", { name: "Upload" }).click();
		cy.wait("@upload_file").its("response.statusCode").should("eq", 200);
		cy.get(".modal:visible").should("not.exist");
	});

	it("should accept uploaded files", () => {
		open_upload_dialog();

		cy.get_open_dialog().findByRole("button", { name: "Library" }).click();
		cy.findByPlaceholderText("Search by filename or extension").type("example.json");
		cy.get_open_dialog().findAllByText("example.json").first().click();
		cy.intercept("POST", "/api/method/upload_file").as("upload_file");
		cy.get_open_dialog().findByRole("button", { name: "Upload" }).click();
		cy.wait("@upload_file")
			.its("response.body.message")
			.should("have.property", "file_name", "example.json");
		cy.get(".modal:visible").should("not.exist");
	});

	it("should accept web links", () => {
		open_upload_dialog();

		cy.get_open_dialog().findByRole("button", { name: "Link" }).click();
		cy.get_open_dialog()
			.findByPlaceholderText("Attach a web link")
			.type("https://github.com", { delay: 100, force: true });
		cy.intercept("POST", "/api/method/upload_file").as("upload_file");
		cy.get_open_dialog().findByRole("button", { name: "Upload" }).click();
		cy.wait("@upload_file")
			.its("response.body.message")
			.should("have.property", "file_url", "https://github.com");
		cy.get(".modal:visible").should("not.exist");
	});

	it("should allow cropping and optimization for valid images", () => {
		open_upload_dialog();

		cy.get_open_dialog()
			.find(".file-upload-area")
			.selectFile("cypress/fixtures/sample_image.jpg", {
				action: "drag-drop",
			});

		cy.get_open_dialog().findAllByText("sample_image.jpg").should("exist");
		cy.get_open_dialog().find(".btn-crop").first().click();
		cy.get_open_dialog().findByRole("button", { name: "Crop" }).click();
		cy.get_open_dialog().findAllByRole("checkbox", { name: "Optimize" }).should("exist");
		cy.get_open_dialog().findAllByLabelText("Optimize").first().click();

		cy.intercept("POST", "/api/method/upload_file").as("upload_file");
		cy.get_open_dialog().findByRole("button", { name: "Upload" }).click();
		cy.wait("@upload_file").its("response.statusCode").should("eq", 200);
		cy.get(".modal:visible").should("not.exist");
	});
});
