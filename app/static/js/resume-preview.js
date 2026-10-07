/* Shared by the student editor, administrator preview and submitted company resumes. */
window.renderResumePreview = function(container, resumeData, currentTemplate) {
    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[char]));
    const isFieldHidden = (section, key) => !!resumeData.hiddenFields?.[section]?.[key];
    const isSkillHidden = skill => !!resumeData.hiddenSkills?.[String(skill)];
    function renderPreviewContact(b) {
        const contacts = [
            (b.phone && !isFieldHidden('basic', 'phone')) ? `电话：${b.phone}` : '',
            (b.email && !isFieldHidden('basic', 'email')) ? `邮箱：${b.email}` : '',
            (b.location && !isFieldHidden('basic', 'location')) ? `城市：${b.location}` : ''
        ].filter(Boolean);

        if (contacts.length === 0) return '';
        const content = contacts.map(item => `<span>${escapeHtml(item)}</span>`).join('');
        return `<div class="tpl-contact">${content}</div>`;
    }

    function renderPreviewSection(title, content) {
        if (!String(content || '').trim()) return '';
        return `
            <section class="tpl-section">
                <div class="tpl-section-title">${title}</div>
                ${content}
            </section>
        `;
    }

    function renderPreviewItem({ title, subtitle = '', date = '', desc = '' }) {
        return `
            <div class="tpl-item">
                <div class="tpl-item-header">
                    <span class="tpl-item-title">${escapeHtml(title)}</span>
                    ${date ? `<span class="tpl-item-date">${escapeHtml(date)}</span>` : ''}
                </div>
                ${subtitle ? `<div class="tpl-item-subtitle">${escapeHtml(subtitle)}</div>` : ''}
                ${desc ? `<div class="tpl-item-desc">${escapeHtml(desc)}</div>` : ''}
            </div>
        `;
    }

    function itemFieldVisible(item, key) {
        if (!item || typeof item !== 'object') return true;
        if (item._hidden) return false;
        if (!item._hiddenFields || typeof item._hiddenFields !== 'object' || Array.isArray(item._hiddenFields)) return true;
        return !item._hiddenFields[key];
    }

    function renderPreviewAwards(items) {
        return items.map(item => {
            const title = itemFieldVisible(item, 'name') ? (item.name || '') : '';
            const rank = itemFieldVisible(item, 'rank') ? (item.rank || '') : '';
            const level = itemFieldVisible(item, 'level') ? (item.level || '') : '';
            if (!String(title || rank || level).trim()) return '';
            return `
                <div class="tpl-item">
                    ${title ? `<div class="tpl-award-title">${escapeHtml(title)}</div>` : ''}
                    ${(rank || level) ? `
                        <div class="tpl-award-meta">
                            ${rank ? `<span class="tpl-chip">${escapeHtml(rank)}</span>` : ''}
                            ${level ? `<span class="tpl-chip">${escapeHtml(level)}</span>` : ''}
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
    }

    function renderPreviewSkills(items) {
        return `<div class="tpl-chip-row">${items.map(skill => `<span class="tpl-chip">${escapeHtml(skill)}</span>`).join('')}</div>`;
    }

    function renderPreviewContentBlock(p, key) {
        const renderers = {
            summary: () => p.showBasic && !isFieldHidden('basic', 'self_evaluation') && p.b.self_evaluation ? `<div class="tpl-item-desc">${escapeHtml(p.b.self_evaluation)}</div>` : '',
            education: () => p.educationItems.map(item => {
                const title = itemFieldVisible(item, 'school') ? (item.school || '') : '';
                const subtitle = itemFieldVisible(item, 'major') ? (item.major || '') : '';
                const date = itemFieldVisible(item, 'date') ? (item.date || '') : '';
                if (!String(title || subtitle || date).trim()) return '';
                return renderPreviewItem({ title, subtitle, date });
            }).join(''),
            experience: () => p.experienceItems.map(item => {
                const title = itemFieldVisible(item, 'company') ? (item.company || '') : '';
                const subtitle = itemFieldVisible(item, 'position') ? (item.position || '') : '';
                const date = itemFieldVisible(item, 'date') ? (item.date || '') : '';
                const desc = itemFieldVisible(item, 'description') ? (item.description || '') : '';
                if (!String(title || subtitle || date || desc).trim()) return '';
                return renderPreviewItem({ title, subtitle, date, desc });
            }).join(''),
            projects: () => p.projectItems.map(item => {
                const title = itemFieldVisible(item, 'name') ? (item.name || '') : '';
                const subtitle = itemFieldVisible(item, 'role') ? (item.role || '') : '';
                const date = itemFieldVisible(item, 'date') ? (item.date || '') : '';
                const desc = itemFieldVisible(item, 'description') ? (item.description || '') : '';
                if (!String(title || subtitle || date || desc).trim()) return '';
                return renderPreviewItem({ title, subtitle, date, desc });
            }).join(''),
            campus: () => p.campusItems.map(item => {
                const title = itemFieldVisible(item, 'organization') ? (item.organization || '') : '';
                const subtitle = itemFieldVisible(item, 'position') ? (item.position || '') : '';
                const desc = itemFieldVisible(item, 'achievements') ? (item.achievements || '') : '';
                if (!String(title || subtitle || desc).trim()) return '';
                return renderPreviewItem({ title, subtitle, desc });
            }).join(''),
            awards: () => renderPreviewAwards(p.awardItems),
            skills: () => p.skillItems.length > 0 ? renderPreviewSkills(p.skillItems) : ''
        };
        return renderers[key] ? renderers[key]() : '';
    }

    function renderPreviewSections(p, sections) {
        const labels = {
            summary: '自我评价',
            education: '教育背景',
            experience: '实习/工作经历',
            projects: '项目经验',
            campus: '校园内经历',
            awards: '获奖',
            skills: '技能与证书'
        };

        return sections.map(key => renderPreviewSection(labels[key], renderPreviewContentBlock(p, key))).join('');
    }

    // --- 预览渲染逻辑 ---

    function renderPreview() {
        const d = resumeData;
        const b = d.basic || {};
        const hidden = d.hiddenSections || {};
        const sectionVisible = (section) => !hidden[section];
        const hasText = (value) => String(value || '').trim().length > 0;
        const filterItems = (items, keys) => (items || []).filter(item => item && !item._hidden && keys.some(key => itemFieldVisible(item, key) && hasText(item[key])));
        const educationItems = filterItems(d.education, ['school', 'major', 'date']);
        const experienceItems = filterItems(d.experience, ['company', 'position', 'date', 'description']);
        const projectItems = filterItems(d.projects, ['name', 'role', 'date', 'description']);
        const campusItems = filterItems(d.campus_experience, ['organization', 'position', 'achievements']);
        const awardItems = filterItems(d.awards, ['name', 'rank', 'level']);
        const skillItems = (d.skills || []).filter(hasText).filter(s => !isSkillHidden(s));
        const showBasic = sectionVisible('basic');
        const showSkills = sectionVisible('skills') && skillItems.length > 0;

        const basicVisible = {
            name: showBasic && !isFieldHidden('basic', 'name'),
            job_target: showBasic && !isFieldHidden('basic', 'job_target'),
            phone: showBasic && !isFieldHidden('basic', 'phone'),
            email: showBasic && !isFieldHidden('basic', 'email'),
            location: showBasic && !isFieldHidden('basic', 'location'),
            self_evaluation: showBasic && !isFieldHidden('basic', 'self_evaluation')
        };
        const hasAnyContact = (basicVisible.phone && hasText(b.phone)) || (basicVisible.email && hasText(b.email)) || (basicVisible.location && hasText(b.location));
        const hasAnyBasicHeader = (basicVisible.name && hasText(b.name)) || (basicVisible.job_target && hasText(b.job_target)) || hasAnyContact;
        const p = {
            b,
            showBasic,
            educationItems: sectionVisible('education') ? educationItems : [],
            experienceItems: sectionVisible('experience') ? experienceItems : [],
            projectItems: sectionVisible('projects') ? projectItems : [],
            campusItems: sectionVisible('campus_experience') ? campusItems : [],
            awardItems: sectionVisible('awards') ? awardItems : [],
            skillItems: showSkills ? skillItems : []
        };

        if (currentTemplate === 'modern') {
            container.innerHTML = `
                <div class="resume-modern">
                    <div class="sidebar">
                        ${showBasic ? `
                            ${basicVisible.name ? `<div class="name" style="margin-bottom:20px; text-align:left;">${escapeHtml(b.name || '姓名')}</div>` : ''}
                            ${(basicVisible.phone && b.phone) || (basicVisible.email && b.email) || (basicVisible.location && b.location) ? `
                                <div class="section-title">联系方式</div>
                                ${basicVisible.phone && b.phone ? `<div class="contact-item">📞 ${escapeHtml(b.phone)}</div>` : ''}
                                ${basicVisible.email && b.email ? `<div class="contact-item">✉️ ${escapeHtml(b.email)}</div>` : ''}
                                ${basicVisible.location && b.location ? `<div class="contact-item">📍 ${escapeHtml(b.location)}</div>` : ''}
                            ` : ''}
                            ${basicVisible.job_target ? `
                                <div class="section-title">求职意向</div>
                                <div class="contact-item">${escapeHtml(b.job_target || '未填写')}</div>
                            ` : ''}
                        ` : ''}

                        ${showSkills ? `
                            <div class="section-title">技能专长</div>
                            <div>
                                ${skillItems.map(s => `<span class="skill-item">${escapeHtml(s)}</span>`).join('')}
                            </div>
                        ` : ''}
                    </div>
                    <div class="main">
                        ${showBasic && basicVisible.self_evaluation ? `
                            <div class="section-title" style="margin-top:0;">自我评价</div>
                            <p class="item-desc">${escapeHtml(b.self_evaluation || '暂无')}</p>
                        ` : ''}

                        ${sectionVisible('experience') && experienceItems.length > 0 ? `<div class="section-title">工作经历</div>` : ''}
                        ${sectionVisible('experience') ? experienceItems.map(item => {
                            const title = itemFieldVisible(item, 'company') ? (item.company || '') : '';
                            const date = itemFieldVisible(item, 'date') ? (item.date || '') : '';
                            const subtitle = itemFieldVisible(item, 'position') ? (item.position || '') : '';
                            const desc = itemFieldVisible(item, 'description') ? (item.description || '') : '';
                            if (!hasText(title) && !hasText(date) && !hasText(subtitle) && !hasText(desc)) return '';
                            const header = (hasText(title) || hasText(date)) ? `
                                <div class="item-header">
                                    <span class="item-title">${escapeHtml(title)}</span>
                                    ${hasText(date) ? `<span class=\"item-date\">${escapeHtml(date)}</span>` : ''}
                                </div>
                            ` : '';
                            return `
                                <div class="item">
                                    ${header}
                                    ${hasText(subtitle) ? `<div class=\"item-subtitle\">${escapeHtml(subtitle)}</div>` : ''}
                                    ${hasText(desc) ? `<div class=\"item-desc\">${escapeHtml(desc)}</div>` : ''}
                                </div>
                            `;
                        }).join('') : ''}

                        ${sectionVisible('projects') && projectItems.length > 0 ? `<div class="section-title">项目经验</div>` : ''}
                        ${sectionVisible('projects') ? projectItems.map(item => {
                            const title = itemFieldVisible(item, 'name') ? (item.name || '') : '';
                            const date = itemFieldVisible(item, 'date') ? (item.date || '') : '';
                            const subtitle = itemFieldVisible(item, 'role') ? (item.role || '') : '';
                            const desc = itemFieldVisible(item, 'description') ? (item.description || '') : '';
                            if (!hasText(title) && !hasText(date) && !hasText(subtitle) && !hasText(desc)) return '';
                            const header = (hasText(title) || hasText(date)) ? `
                                <div class="item-header">
                                    <span class="item-title">${escapeHtml(title)}</span>
                                    ${hasText(date) ? `<span class=\"item-date\">${escapeHtml(date)}</span>` : ''}
                                </div>
                            ` : '';
                            return `
                                <div class="item">
                                    ${header}
                                    ${hasText(subtitle) ? `<div class=\"item-subtitle\">${escapeHtml(subtitle)}</div>` : ''}
                                    ${hasText(desc) ? `<div class=\"item-desc\">${escapeHtml(desc)}</div>` : ''}
                                </div>
                            `;
                        }).join('') : ''}

                        ${sectionVisible('campus_experience') && campusItems.length > 0 ? `<div class="section-title">校园内经历</div>` : ''}
                        ${sectionVisible('campus_experience') ? campusItems.map(item => {
                            const title = itemFieldVisible(item, 'organization') ? (item.organization || '') : '';
                            const subtitle = itemFieldVisible(item, 'position') ? (item.position || '') : '';
                            const desc = itemFieldVisible(item, 'achievements') ? (item.achievements || '') : '';
                            if (!hasText(title) && !hasText(subtitle) && !hasText(desc)) return '';
                            const header = hasText(title) ? `
                                <div class="item-header">
                                    <span class="item-title">${escapeHtml(title)}</span>
                                </div>
                            ` : '';
                            return `
                                <div class="item">
                                    ${header}
                                    ${hasText(subtitle) ? `<div class=\"item-subtitle\">${escapeHtml(subtitle)}</div>` : ''}
                                    ${hasText(desc) ? `<div class=\"item-desc\">${escapeHtml(desc)}</div>` : ''}
                                </div>
                            `;
                        }).join('') : ''}

                        ${sectionVisible('awards') && awardItems.length > 0 ? `<div class="section-title">获奖</div>` : ''}
                        ${sectionVisible('awards') ? awardItems.map(item => {
                            const title = itemFieldVisible(item, 'name') ? (item.name || '') : '';
                            const rank = itemFieldVisible(item, 'rank') ? (item.rank || '') : '';
                            const level = itemFieldVisible(item, 'level') ? (item.level || '') : '';
                            if (!hasText(title) && !hasText(rank) && !hasText(level)) return '';
                            return `
                                <div class="award-item">
                                    ${hasText(title) ? `<div class=\"award-title\">${escapeHtml(title)}</div>` : ''}
                                    ${(hasText(rank) || hasText(level)) ? `
                                        <div class="award-meta">
                                            ${hasText(rank) ? `<span class=\"award-badge\">${escapeHtml(rank)}</span>` : ''}
                                            ${hasText(level) ? `<span class=\"award-badge\">${escapeHtml(level)}</span>` : ''}
                                        </div>
                                    ` : ''}
                                </div>
                            `;
                        }).join('') : ''}

                        ${sectionVisible('education') && educationItems.length > 0 ? `<div class="section-title">教育背景</div>` : ''}
                        ${sectionVisible('education') ? educationItems.map(item => {
                            const title = itemFieldVisible(item, 'school') ? (item.school || '') : '';
                            const date = itemFieldVisible(item, 'date') ? (item.date || '') : '';
                            const subtitle = itemFieldVisible(item, 'major') ? (item.major || '') : '';
                            if (!hasText(title) && !hasText(date) && !hasText(subtitle)) return '';
                            const header = (hasText(title) || hasText(date)) ? `
                                <div class="item-header">
                                    <span class="item-title">${escapeHtml(title)}</span>
                                    ${hasText(date) ? `<span class=\"item-date\">${escapeHtml(date)}</span>` : ''}
                                </div>
                            ` : '';
                            return `
                                <div class="item">
                                    ${header}
                                    ${hasText(subtitle) ? `<div class=\"item-subtitle\">${escapeHtml(subtitle)}</div>` : ''}
                                </div>
                            `;
                        }).join('') : ''}
                    </div>
                </div>
            `;
        } else if (currentTemplate === 'ats') {
            container.innerHTML = `
                <div class="resume-ats">
                    ${p.showBasic && hasAnyBasicHeader ? `
                        <header class="ats-header">
                            ${basicVisible.name ? `<div class="ats-name">${escapeHtml(b.name || '姓名')}</div>` : ''}
                            ${basicVisible.job_target ? `<div class="ats-target">${escapeHtml(b.job_target || '求职意向')}</div>` : ''}
                            ${renderPreviewContact(b)}
                        </header>
                    ` : ''}
                    ${renderPreviewSections(p, ['summary', 'education', 'experience', 'projects', 'campus', 'awards', 'skills'])}
                </div>
            `;
        } else if (currentTemplate === 'minimal') {
            container.innerHTML = `
                <div class="resume-minimal">
                    ${p.showBasic && hasAnyBasicHeader ? `
                        <header class="minimal-header">
                            ${basicVisible.name ? `<div class="minimal-name">${escapeHtml(b.name || '姓名')}</div>` : ''}
                            ${basicVisible.job_target ? `<div class="minimal-target">${escapeHtml(b.job_target || '')}</div>` : ''}
                            ${renderPreviewContact(b)}
                        </header>
                    ` : ''}
                    ${renderPreviewSections(p, ['summary', 'experience', 'projects', 'campus', 'awards', 'education', 'skills'])}
                </div>
            `;
        } else if (currentTemplate === 'campus') {
            container.innerHTML = `
                <div class="resume-campus">
                    ${p.showBasic && hasAnyBasicHeader ? `
                        <header class="campus-header">
                            <div>
                                ${basicVisible.name ? `<div class="campus-name">${escapeHtml(b.name || '姓名')}</div>` : ''}
                                ${basicVisible.job_target ? `<div class="campus-target">${escapeHtml(b.job_target || '求职意向')}</div>` : ''}
                            </div>
                            ${renderPreviewContact(b)}
                        </header>
                    ` : ''}
                    ${renderPreviewSections(p, ['summary', 'education', 'campus', 'awards', 'projects', 'experience', 'skills'])}
                </div>
            `;
        } else if (currentTemplate === 'business') {
            container.innerHTML = `
                <div class="resume-business">
                    <aside class="business-side">
                        ${p.showBasic && hasAnyBasicHeader ? `
                            ${basicVisible.name ? `<div class="business-name">${escapeHtml(b.name || '姓名')}</div>` : ''}
                            ${basicVisible.job_target ? `<div class="business-target">${escapeHtml(b.job_target || '')}</div>` : ''}
                            ${renderPreviewSection('联系方式', renderPreviewContact(b))}
                        ` : ''}
                        ${renderPreviewSections(p, ['skills', 'awards'])}
                    </aside>
                    <main class="business-main">
                        ${renderPreviewSections(p, ['summary', 'experience', 'projects', 'campus', 'education'])}
                    </main>
                </div>
            `;
        } else if (currentTemplate === 'creative') {
            container.innerHTML = `
                <div class="resume-creative">
                    ${p.showBasic && hasAnyBasicHeader ? `
                        <header class="creative-header">
                            ${basicVisible.name ? `<div class="creative-name">${escapeHtml(b.name || '姓名')}</div>` : ''}
                            ${basicVisible.job_target ? `<div class="creative-target">${escapeHtml(b.job_target || '求职意向')}</div>` : ''}
                            ${renderPreviewContact(b)}
                        </header>
                    ` : ''}
                    <div class="creative-body">
                        ${renderPreviewSections(p, ['summary', 'projects', 'experience', 'campus', 'awards', 'education', 'skills'])}
                    </div>
                </div>
            `;
        } else if (currentTemplate === 'tech') {
            container.innerHTML = `
                <div class="resume-tech">
                    <aside class="tech-side">
                        ${p.showBasic && hasAnyBasicHeader ? `
                            ${basicVisible.name ? `<div class="tech-name">${escapeHtml(b.name || '姓名')}</div>` : ''}
                            ${basicVisible.job_target ? `<div class="tech-target">${escapeHtml(b.job_target || '')}</div>` : ''}
                            ${renderPreviewSection('联系方式', renderPreviewContact(b))}
                        ` : ''}
                        ${renderPreviewSections(p, ['skills', 'awards'])}
                    </aside>
                    <main class="tech-main">
                        ${renderPreviewSections(p, ['summary', 'projects', 'experience', 'campus', 'education'])}
                    </main>
                </div>
            `;
        } else {
            // Classic Template
            const classicContacts = [
                (b.phone && !isFieldHidden('basic', 'phone')) ? b.phone : '',
                (b.email && !isFieldHidden('basic', 'email')) ? b.email : '',
                (b.location && !isFieldHidden('basic', 'location')) ? b.location : ''
            ].filter(v => hasText(v)).join(' | ');
            container.innerHTML = `
                <div class="resume-classic">
                    ${showBasic ? `
                        ${hasAnyBasicHeader ? `
                            <div class="header">
                                ${basicVisible.name ? `<div class="name">${escapeHtml(b.name || '姓名')}</div>` : ''}
                                ${classicContacts ? `<div class="contact">${escapeHtml(classicContacts)}</div>` : ''}
                                ${basicVisible.job_target ? `<div class="contact">求职意向：${escapeHtml(b.job_target || '')}</div>` : ''}
                            </div>
                        ` : ''}

                        ${basicVisible.self_evaluation ? `
                            <div class="section-title">自我评价</div>
                            <p class="item-desc">${escapeHtml(b.self_evaluation || '')}</p>
                        ` : ''}
                    ` : ''}

                    ${sectionVisible('education') && educationItems.length > 0 ? `<div class="section-title">教育背景</div>` : ''}
                    ${sectionVisible('education') ? educationItems.map(item => `
                        <div class="item">
                            <div class="item-header">
                                <span>${escapeHtml(itemFieldVisible(item, 'school') ? item.school || '' : '')} - ${escapeHtml(itemFieldVisible(item, 'major') ? item.major || '' : '')}</span>
                                <span>${escapeHtml(itemFieldVisible(item, 'date') ? item.date || '' : '')}</span>
                            </div>
                        </div>
                    `).join('') : ''}

                    ${sectionVisible('experience') && experienceItems.length > 0 ? `<div class="section-title">工作经历</div>` : ''}
                    ${sectionVisible('experience') ? experienceItems.map(item => `
                        <div class="item">
                            <div class="item-header">
                                <span>${escapeHtml(itemFieldVisible(item, 'company') ? item.company || '' : '')} - ${escapeHtml(itemFieldVisible(item, 'position') ? item.position || '' : '')}</span>
                                <span>${escapeHtml(itemFieldVisible(item, 'date') ? item.date || '' : '')}</span>
                            </div>
                            <div class="item-desc">${escapeHtml(itemFieldVisible(item, 'description') ? item.description || '' : '')}</div>
                        </div>
                    `).join('') : ''}

                    ${sectionVisible('projects') && projectItems.length > 0 ? `<div class="section-title">项目经验</div>` : ''}
                    ${sectionVisible('projects') ? projectItems.map(item => `
                        <div class="item">
                            <div class="item-header">
                                <span>${escapeHtml(itemFieldVisible(item, 'name') ? item.name || '' : '')} - ${escapeHtml(itemFieldVisible(item, 'role') ? item.role || '' : '')}</span>
                                <span>${escapeHtml(itemFieldVisible(item, 'date') ? item.date || '' : '')}</span>
                            </div>
                            <div class="item-desc">${escapeHtml(itemFieldVisible(item, 'description') ? item.description || '' : '')}</div>
                        </div>
                    `).join('') : ''}

                    ${sectionVisible('campus_experience') && campusItems.length > 0 ? `<div class="section-title">校园内经历</div>` : ''}
                    ${sectionVisible('campus_experience') ? campusItems.map(item => `
                        <div class="item">
                            <div class="item-header">
                                <span>${escapeHtml(itemFieldVisible(item, 'organization') ? item.organization || '' : '')} - ${escapeHtml(itemFieldVisible(item, 'position') ? item.position || '' : '')}</span>
                            </div>
                            <div class="item-desc">${escapeHtml(itemFieldVisible(item, 'achievements') ? item.achievements || '' : '')}</div>
                        </div>
                    `).join('') : ''}

                    ${sectionVisible('awards') && awardItems.length > 0 ? `<div class="section-title">获奖</div>` : ''}
                    ${sectionVisible('awards') ? awardItems.map(item => `
                        <div class="item">
                            <div class="item-header">
                                <span>${escapeHtml(itemFieldVisible(item, 'name') ? item.name || '' : '')} - ${escapeHtml(itemFieldVisible(item, 'rank') ? item.rank || '' : '')}</span>
                                <span>${escapeHtml(itemFieldVisible(item, 'level') ? item.level || '' : '')}</span>
                            </div>
                        </div>
                    `).join('') : ''}

                    ${showSkills ? `
                        <div class="section-title">技能</div>
                        <p class="item-desc">${skillItems.map(escapeHtml).join(' / ')}</p>
                    ` : ''}
                </div>
            `;
        }


    }

    renderPreview();
};
